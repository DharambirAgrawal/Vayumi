import { and, eq, isNull } from "drizzle-orm";
import { db } from "../../core/db/index.js";
import { sessions } from "../../core/db/schema/index.js";
import { AuthError, NotFoundError } from "../../core/errors/index.js";
import { cache } from "../../core/redis/helpers.js";
import { redis } from "../../core/redis/index.js";
import { RedisKeys, RedisTTL } from "../../core/redis/keys.js";
import type { SessionView } from "./sessions.types.js";

const toView = (session: typeof sessions.$inferSelect, currentSessionId: string): SessionView => ({
  id: session.id,
  device_type: session.deviceType,
  device_name: session.deviceName,
  device_fingerprint: session.deviceFingerprint,
  last_seen_at: session.lastSeenAt,
  created_at: session.createdAt,
  expires_at: session.expiresAt,
  is_current: session.id === currentSessionId,
});

export const sessionsService = {
  async list(userId: string, currentSessionId: string) {
    const rows = await cache.remember(
      RedisKeys.userSessions(userId),
      RedisTTL.userSessions,
      () =>
        db
          .select()
          .from(sessions)
          .where(and(eq(sessions.userId, userId), eq(sessions.isActive, true), isNull(sessions.revokedAt))),
    );

    return { sessions: rows.map((session) => toView(session, currentSessionId)) };
  },

  async revoke(userId: string, sessionId: string, currentSessionId: string) {
    if (sessionId === currentSessionId) {
      throw new AuthError("Use /auth/logout to revoke the current session");
    }

    const [session] = await db
      .select()
      .from(sessions)
      .where(and(eq(sessions.id, sessionId), eq(sessions.userId, userId), eq(sessions.isActive, true)))
      .limit(1);

    if (!session) {
      throw new NotFoundError("Session");
    }

    await db
      .update(sessions)
      .set({ isActive: false, revokedAt: new Date(), updatedAt: new Date() })
      .where(eq(sessions.id, session.id));

    await Promise.all([
      redis.del(RedisKeys.refreshToken(session.id)),
      cache.invalidate(RedisKeys.userSessions(userId)),
    ]);

    return { success: true };
  },
};
