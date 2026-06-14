/** HTTP retry schedule for Server 2 agent event calls (1s, 2s backoff). */
export const SERVER2_AGENT_EVENT_FETCH = {
  attempts: 3,
  backoffMs: [1000, 2000] as const,
} as const;
