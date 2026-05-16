import { eq } from "drizzle-orm";
import { db } from "../../core/db/index.js";
import { userSettings } from "../../core/db/schema/index.js";
import { AppError } from "../../core/errors/index.js";
import { cache } from "../../core/redis/helpers.js";
import { RedisKeys, RedisTTL } from "../../core/redis/keys.js";
import type { SettingsPatchInput } from "./settings.validators.js";
import type { UserSettingsView } from "./settings.types.js";

const toView = (settings: typeof userSettings.$inferSelect): UserSettingsView => ({
  notifications: settings.notifications ?? {},
  privacy: settings.privacy ?? {},
  appearance: settings.appearance ?? {},
  updated_at: settings.updatedAt,
});

const ensureSettings = async (userId: string) => {
  const [existing] = await db.select().from(userSettings).where(eq(userSettings.userId, userId)).limit(1);
  if (existing) {
    return existing;
  }

  const [created] = await db.insert(userSettings).values({ userId }).returning();
  if (!created) {
    throw new AppError(500, "SETTINGS_CREATE_FAILED", "Unable to create settings");
  }

  return created;
};

export const settingsService = {
  async getSettings(userId: string) {
    const settings = await cache.remember(
      RedisKeys.userSettings(userId),
      RedisTTL.userSettings,
      () => ensureSettings(userId),
    );

    return { settings: toView(settings) };
  },

  async updateNotifications(userId: string, input: SettingsPatchInput) {
    const current = await ensureSettings(userId);
    const next = { ...(current.notifications ?? {}), ...input };

    const [updated] = await db
      .update(userSettings)
      .set({ notifications: next, updatedAt: new Date() })
      .where(eq(userSettings.userId, userId))
      .returning();

    if (!updated) {
      throw new AppError(500, "SETTINGS_UPDATE_FAILED", "Unable to update settings");
    }

    await cache.invalidate(RedisKeys.userSettings(userId));
    return { settings: toView(updated) };
  },

  async updatePrivacy(userId: string, input: SettingsPatchInput) {
    const current = await ensureSettings(userId);
    const next = { ...(current.privacy ?? {}), ...input };

    const [updated] = await db
      .update(userSettings)
      .set({ privacy: next, updatedAt: new Date() })
      .where(eq(userSettings.userId, userId))
      .returning();

    if (!updated) {
      throw new AppError(500, "SETTINGS_UPDATE_FAILED", "Unable to update settings");
    }

    await cache.invalidate(RedisKeys.userSettings(userId));
    return { settings: toView(updated) };
  },

  async updateAppearance(userId: string, input: SettingsPatchInput) {
    const current = await ensureSettings(userId);
    const next = { ...(current.appearance ?? {}), ...input };

    const [updated] = await db
      .update(userSettings)
      .set({ appearance: next, updatedAt: new Date() })
      .where(eq(userSettings.userId, userId))
      .returning();

    if (!updated) {
      throw new AppError(500, "SETTINGS_UPDATE_FAILED", "Unable to update settings");
    }

    await cache.invalidate(RedisKeys.userSettings(userId));
    return { settings: toView(updated) };
  },
};
