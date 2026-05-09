import { and, eq } from "drizzle-orm";
import { db } from "../../core/db/index.js";
import { pushTokens } from "../../core/db/schema/index.js";
import type { RegisterPushTokenInput, RemovePushTokenInput } from "./notifications.validators.js";

export const notificationsService = {
  async registerPushToken(userId: string, sessionId: string, input: RegisterPushTokenInput) {
    const [token] = await db
      .insert(pushTokens)
      .values({
        userId,
        sessionId,
        token: input.token,
        platform: input.platform,
      })
      .onConflictDoUpdate({
        target: pushTokens.token,
        set: {
          userId,
          sessionId,
          platform: input.platform,
          updatedAt: new Date(),
        },
      })
      .returning();

    return { push_token: token };
  },

  async removePushToken(userId: string, input: RemovePushTokenInput) {
    await db.delete(pushTokens).where(and(eq(pushTokens.userId, userId), eq(pushTokens.token, input.token)));
    return { success: true };
  },
};
