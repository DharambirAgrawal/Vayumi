import type { NextFunction, Request, Response } from "express";
import { AppError } from "../errors/index.js";
import { redis } from "../redis/index.js";
import { RedisKeys } from "../redis/keys.js";
import { logger } from "../utils/logger.js";

type RateLimitOptions = {
  windowSeconds: number;
  max: number;
  keyPrefix?: string;
  keyBy?: (req: Request) => string;
};

export const rateLimiter =
  ({ windowSeconds, max, keyPrefix = "ip", keyBy }: RateLimitOptions) =>
  async (req: Request, _res: Response, next: NextFunction) => {
    try {
      const identity = keyBy?.(req) ?? req.ip ?? "unknown";
      const key = keyPrefix === "user" ? RedisKeys.rateLimitUser(identity) : RedisKeys.rateLimitIP(`${keyPrefix}:${identity}`);
      const count = await redis.incr(key);

      if (count === 1) {
        await redis.expire(key, windowSeconds);
      }

      if (count > max) {
        next(new AppError(429, "RATE_LIMITED", "Too many requests"));
        return;
      }

      next();
    } catch (error) {
      logger.warn(
        {
          error,
          keyPrefix,
          path: req.originalUrl,
          method: req.method,
        },
        "Rate limiter unavailable, allowing request",
      );
      next();
    }
  };
