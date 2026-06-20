/** HTTP retry schedules aligned with PLAN (classify: 2s, 4s — notify: 1s, 2s). */
export const SERVER2_CLASSIFY_FETCH = {
  attempts: 3,
  backoffMs: [2000, 4000] as const,
} as const;

export const SERVER2_NOTIFY_FETCH = {
  attempts: 3,
  backoffMs: [1000, 2000] as const,
} as const;

export const EMAIL_CLASSIFY_MAX_BODY_CHARS = 2000;
export const EMAIL_AI_CLASSIFY_TIMEOUT_MS = 3000;
export const EMAIL_NOTIFY_TIMEOUT_MS = 2000;
