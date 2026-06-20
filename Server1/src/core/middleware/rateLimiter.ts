import type { NextFunction, Request, Response } from "express";
import { AppError } from "../errors/index.js";
import { sql } from "../db/index.js";
import { logger } from "../utils/logger.js";

type RateLimitOptions = {
  windowSeconds: number;
  max: number;
  keyPrefix?: string;
  keyBy?: (req: Request) => string;
};

/**
 * Fixed-window rate limiter backed by Postgres. The upsert is atomic: a single
 * row per key tracks the current count and window expiry, resetting once the
 * window lapses. Fails open — if the database is unreachable the request is
 * allowed rather than blocked.
 */
export const rateLimiter =
  ({ windowSeconds, max, keyPrefix = "ip", keyBy }: RateLimitOptions) =>
  async (req: Request, _res: Response, next: NextFunction) => {
    try {
      const identity = keyBy?.(req) ?? req.ip ?? "unknown";
      const key = `${keyPrefix}:${identity}`;

      const [row] = await sql<{ count: number }[]>`
        insert into rate_limits ("key", "count", "expires_at")
        values (${key}, 1, now() + make_interval(secs => ${windowSeconds}))
        on conflict ("key") do update set
          "count" = case
            when rate_limits.expires_at < now() then 1
            else rate_limits.count + 1
          end,
          "expires_at" = case
            when rate_limits.expires_at < now() then now() + make_interval(secs => ${windowSeconds})
            else rate_limits.expires_at
          end
        returning "count"
      `;

      if (row && row.count > max) {
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
