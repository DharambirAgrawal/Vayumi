import { and, eq, lt } from "drizzle-orm";
import { db } from "../../../core/db/index.js";
import { emailVerifications, passwordResetTokens, rateLimits, sessions } from "../../../core/db/schema/index.js";
import { logger } from "../../../core/utils/logger.js";
import type { CronJobDefinition } from "../cron.types.js";

export const cleanExpiredTokensJob: CronJobDefinition = {
  name: "clean-expired-tokens",
  schedule: "0 3 * * *",
  async run() {
    const now = new Date();

    const expiredSessions = await db
      .update(sessions)
      .set({ isActive: false, revokedAt: now, updatedAt: now })
      .where(and(eq(sessions.isActive, true), lt(sessions.expiresAt, now)))
      .returning({ id: sessions.id });

    const expiredEmailTokens = await db
      .delete(emailVerifications)
      .where(lt(emailVerifications.expiresAt, now))
      .returning({ id: emailVerifications.id });

    const expiredResetTokens = await db
      .delete(passwordResetTokens)
      .where(lt(passwordResetTokens.expiresAt, now))
      .returning({ id: passwordResetTokens.id });

    const expiredRateLimits = await db
      .delete(rateLimits)
      .where(lt(rateLimits.expiresAt, now))
      .returning({ key: rateLimits.key });

    logger.info(
      {
        expiredSessions: expiredSessions.length,
        expiredEmailTokens: expiredEmailTokens.length,
        expiredResetTokens: expiredResetTokens.length,
        expiredRateLimits: expiredRateLimits.length,
      },
      "Expired auth tokens cleaned",
    );
  },
};
