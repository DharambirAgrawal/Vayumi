import { env } from "./index.js";

export const remindersConfig = {
  internalReminderSecret: env.INTERNAL_REMINDER_SECRET,
  fireBatchSize: env.REMINDER_FIRE_BATCH_SIZE,
  agentEventTimeoutMs: env.REMINDER_AGENT_EVENT_TIMEOUT_MS,
};
