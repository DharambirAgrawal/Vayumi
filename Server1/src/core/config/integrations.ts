import { env } from "./index.js";

const trimTrailingSlash = (value: string) => value.replace(/\/$/, "");

export const integrationsConfig = {
  server2InternalBaseUrl: env.SERVER2_INTERNAL_URL.trim()
    ? trimTrailingSlash(env.SERVER2_INTERNAL_URL.trim())
    : "",
  emailSyncWindowDays: env.EMAIL_SYNC_WINDOW_DAYS,
  emailAiClassifyTimeoutMs: env.EMAIL_AI_CLASSIFY_TIMEOUT_MS,
  emailNotifyTimeoutMs: env.EMAIL_NOTIFY_TIMEOUT_MS,
  emailPollIntervalMinutes: env.EMAIL_POLL_INTERVAL_MINUTES,
  emailClassifyMaxBodyChars: env.EMAIL_CLASSIFY_MAX_BODY_CHARS,
};
