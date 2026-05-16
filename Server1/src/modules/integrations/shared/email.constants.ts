/** HTTP retry schedules aligned with PLAN (classify: 2s, 4s — notify: 1s, 2s). */
export const SERVER2_CLASSIFY_FETCH = {
  attempts: 3,
  backoffMs: [2000, 4000] as const,
} as const;

export const SERVER2_NOTIFY_FETCH = {
  attempts: 3,
  backoffMs: [1000, 2000] as const,
} as const;
