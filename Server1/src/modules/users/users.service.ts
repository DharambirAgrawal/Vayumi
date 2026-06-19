import { randomUUID } from "node:crypto";
import { and, eq, isNull } from "drizzle-orm";
import { db } from "../../core/db/index.js";
import { sessions, users } from "../../core/db/schema/index.js";
import { NotFoundError, ValidationError } from "../../core/errors/index.js";
import { cache } from "../../core/redis/helpers.js";
import { redis } from "../../core/redis/index.js";
import { RedisKeys, RedisTTL } from "../../core/redis/keys.js";
import type { AccessTokenPayload } from "../../core/types/index.js";
import { uploadPublicFile } from "../../core/utils/storage.js";
import type { UpdateProfileInput } from "./users.validators.js";
import type { UserProfile } from "./users.types.js";

const MAX_AVATAR_BYTES = 5 * 1024 * 1024;
const avatarMimeTypes = new Map([
  ["image/jpeg", "jpg"],
  ["image/png", "png"],
  ["image/webp", "webp"],
]);

const toProfile = (user: typeof users.$inferSelect): UserProfile => ({
  id: user.id,
  email: user.email,
  name: user.name,
  avatar_url: user.avatarUrl,
  is_verified: user.isVerified,
  created_at: user.createdAt,
  updated_at: user.updatedAt,
});

const blockAccessToken = async (token: AccessTokenPayload) => {
  if (!token.exp) {
    return;
  }
  const ttl = Math.max(token.exp - Math.floor(Date.now() / 1000), 1);
  await redis.set(RedisKeys.tokenBlocklist(token.jti), "1", "EX", ttl);
};

const ensureActiveUser = async (userId: string) => {
  const [user] = await db
    .select()
    .from(users)
    .where(and(eq(users.id, userId), isNull(users.deletedAt)))
    .limit(1);

  if (!user) {
    throw new NotFoundError("User");
  }

  return user;
};

export const usersService = {
  async getProfile(userId: string) {
    const user = await cache.remember(RedisKeys.userProfile(userId), RedisTTL.userProfile, () => ensureActiveUser(userId));
    return { user: toProfile(user) };
  },

  async updateProfile(userId: string, input: UpdateProfileInput) {
    const update: Partial<typeof users.$inferInsert> = { updatedAt: new Date() };

    if (input.name !== undefined) {
      update.name = input.name;
    }

    if (input.avatar_url !== undefined) {
      update.avatarUrl = input.avatar_url;
    }

    const [user] = await db
      .update(users)
      .set(update)
      .where(and(eq(users.id, userId), isNull(users.deletedAt)))
      .returning();

    if (!user) {
      throw new NotFoundError("User");
    }

    await cache.invalidate(RedisKeys.userProfile(userId));
    return { user: toProfile(user) };
  },

  async uploadAvatar(userId: string, file?: Express.Multer.File) {
    if (!file) {
      throw new ValidationError("Avatar file is required");
    }

    if (!file.size) {
      throw new ValidationError("Avatar file is empty");
    }

    if (file.size > MAX_AVATAR_BYTES) {
      throw new ValidationError("Avatar file is too large");
    }

    const extension = avatarMimeTypes.get(file.mimetype);
    if (!extension) {
      throw new ValidationError("Unsupported avatar file type");
    }

    const key = `avatars/${userId}/${randomUUID()}.${extension}`;
    const avatarUrl = await uploadPublicFile({
      key,
      body: file.buffer,
      contentType: file.mimetype,
    });

    const [user] = await db
      .update(users)
      .set({ avatarUrl, updatedAt: new Date() })
      .where(and(eq(users.id, userId), isNull(users.deletedAt)))
      .returning();

    if (!user) {
      throw new NotFoundError("User");
    }

    await cache.invalidate(RedisKeys.userProfile(userId));
    return { avatar_url: avatarUrl };
  },

  async deleteAccount(userId: string, token: AccessTokenPayload) {
    // Hard delete: store/policy compliance requires that deleting an account
    // actually removes the user's data, not just flags it. The `users` row
    // is the cascade root — ON DELETE CASCADE on reminders/meetings/settings/
    // identities/push-tokens/synced-emails/etc. clears everything else.
    const sessionIds = await db.transaction(async (tx) => {
      const [user] = await tx.select({ id: users.id }).from(users).where(eq(users.id, userId)).limit(1);

      if (!user) {
        throw new NotFoundError("User");
      }

      const rows = await tx.select({ id: sessions.id }).from(sessions).where(eq(sessions.userId, userId));

      await tx.delete(users).where(eq(users.id, userId));

      return rows.map((row) => row.id);
    });

    await Promise.all(sessionIds.map((sessionId) => redis.del(RedisKeys.refreshToken(sessionId))));
    await blockAccessToken(token);
    await cache.invalidate(
      RedisKeys.userProfile(userId),
      RedisKeys.userSessions(userId),
      RedisKeys.userSettings(userId),
    );

    return { success: true };
  },
};
