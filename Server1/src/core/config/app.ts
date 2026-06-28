import { env } from "./index.js";

export const appConfig = {
  nodeEnv: env.NODE_ENV,
  port: env.PORT,
  appUrl: env.APP_URL.replace(/\/$/, ""),
  cors: {
    origins: env.ALLOWED_ORIGINS.split(",").map((origin) => origin.trim()).filter(Boolean),
  },
  rateLimit: {
    global: { windowSeconds: 60, max: 300 },
    auth: { windowSeconds: 60, max: 10 },
    // Registration: throttle automated signup floods (per IP).
    register: { windowSeconds: 60 * 60, max: 10 },
    // Email-sending endpoints (forgot password, resend verification): tight and
    // keyed by EMAIL so nobody can inbox-bomb a victim.
    emailDispatch: { windowSeconds: 15 * 60, max: 3 },
  },
  // Centralized input bounds. Tweak here instead of editing each validator.
  limits: {
    meeting: {
      titleMax: 255,
      summaryMax: 20_000,
      /** Per transcript segment text. */
      transcriptSegmentTextMax: 10_000,
      /** Max number of transcript segments per meeting. */
      transcriptSegmentsMax: 5_000,
      /** Each key-point / action-item string. */
      listItemMax: 2_000,
      /** Max key-points / action-items / suggested-reminders entries. */
      listCountMax: 500,
    },
    life: {
      /** Tab display name. */
      tabNameMax: 120,
      /** Tab purpose / description. */
      purposeMax: 1_000,
      /** Serialized tab schema (jsonb) bytes. */
      schemaBytesMax: 32 * 1024,
      /** Serialized entry data (jsonb) bytes. */
      entryDataBytesMax: 16 * 1024,
      /** Raw user input kept for audit. */
      rawInputMax: 5_000,
      /** Max tabs/entries accepted in one bulk sync push. */
      syncTabsMax: 200,
      syncEntriesMax: 2_000,
    },
    memory: {
      keyMax: 120,
      valueMax: 500,
      /** Max facts accepted in one bulk sync push (device caps at ~50). */
      syncFactsMax: 200,
    },
    ai: {
      /** Per-user cloud LLM request caps (one tool-loop round = one request). */
      dailyLimit: env.AI_CLOUD_DAILY_LIMIT,
      minuteLimit: env.AI_CLOUD_MINUTE_LIMIT,
      requestTimeoutMs: env.AI_CLOUD_TIMEOUT_MS,
      /** Request-shape caps to keep payloads sane. */
      maxMessages: 80,
      maxTools: 60,
      maxBodyChars: 60_000,
      maxOutputTokens: 2048,
      /** When non-empty, ONLY these emails may use the cloud AI (lock to yourself). */
      allowedEmails: (env.AI_CLOUD_ALLOWED_EMAILS ?? "")
        .split(",")
        .map((e) => e.trim().toLowerCase())
        .filter(Boolean),
    },
    settings: {
      maxKeys: 100,
      maxSerializedBytes: 64 * 1024,
    },
    upload: {
      avatarMaxBytes: 5 * 1024 * 1024,
    },
  },
};
