import { redis } from "../../../core/redis/index.js";
import { RedisKeys, RedisTTL } from "../../../core/redis/keys.js";

export const emailSyncLock = {
  tryAcquire: (userId: string, provider: string) =>
    redis.setIfNotExists(RedisKeys.emailSyncLock(userId, provider), "1", RedisTTL.emailSyncLock),

  release: async (userId: string, provider: string) => {
    await redis.del(RedisKeys.emailSyncLock(userId, provider));
  },
};
