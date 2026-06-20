/**
 * Per-user/provider email-sync lock. In-process only — sufficient for a single
 * instance. The email integrations are not yet wired up, so this is currently
 * unused; revisit if sync runs across multiple instances.
 */
const held = new Set<string>();

const lockKey = (userId: string, provider: string) => `${userId}:${provider}`;

export const emailSyncLock = {
  tryAcquire: async (userId: string, provider: string): Promise<boolean> => {
    const key = lockKey(userId, provider);
    if (held.has(key)) {
      return false;
    }
    held.add(key);
    return true;
  },

  release: async (userId: string, provider: string) => {
    held.delete(lockKey(userId, provider));
  },
};
