import { and, eq } from "drizzle-orm";
import { db } from "../../core/db/index.js";
import { pushTokens } from "../../core/db/schema/index.js";
import { fcmProvider } from "./fcm.provider.js";
import type { RegisterPushTokenInput, RemovePushTokenInput } from "./notifications.validators.js";

export const notificationsService = {
  async sendPushToUser(
    userId: string,
    input: { title: string; body: string; data?: Record<string, string> },
  ) {
    const tokens = await db.select().from(pushTokens).where(eq(pushTokens.userId, userId));

    if (tokens.length === 0) {
      return false;
    }

    const results = await Promise.allSettled(
      tokens.map((row) =>
        fcmProvider.sendPush({
          token: row.token,
          title: input.title,
          body: input.body,
          ...(input.data ? { data: input.data } : {}),
        }),
      ),
    );

    return results.some((result) => result.status === "fulfilled" && result.value.success);
  },

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
