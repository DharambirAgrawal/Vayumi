import {
  createClient,
  type RedisClientOptions,
} from "redis";
import { env } from "../config/index.js";
import { logger } from "../utils/logger.js";

type SetMode = "EX";
type AppRedisClient = ReturnType<typeof createClient>;

class RedisClientAdapter {
  private readonly client: AppRedisClient;
  public status: "wait" | "ready" | "end" = "wait";

  constructor(client: AppRedisClient) {
    this.client = client;

    this.client.on("connect", () => {
      this.status = "ready";
      logger.info("Redis socket connected");
    });

    this.client.on("ready", () => {
      this.status = "ready";
      logger.info("Redis client ready");
    });

    this.client.on("end", () => {
      this.status = "end";
      logger.warn("Redis connection closed");
    });
  }

  on(event: "error", listener: (error: Error) => void) {
    this.client.on(event, listener);
    return this;
  }

  async connect() {
    if (this.client.isOpen) {
      this.status = "ready";
      return;
    }

    await this.client.connect();
    this.status = "ready";
  }

  async quit() {
    if (!this.client.isOpen) {
      this.status = "end";
      return;
    }

    await this.client.quit();
    this.status = "end";
  }

  disconnect() {
    this.client.destroy();
    this.status = "end";
  }

  async get(key: string) {
    return this.client.get(key);
  }

  async set(key: string, value: string, mode?: SetMode, ttlSeconds?: number) {
    if (mode === "EX" && ttlSeconds) {
      await this.client.set(key, value, { expiration: { type: "EX", value: ttlSeconds } });
      return "OK";
    }

    await this.client.set(key, value);
    return "OK";
  }

  /** SET key value NX EX ttl — returns true if the lock/value was acquired. */
  async setIfNotExists(key: string, value: string, ttlSeconds: number): Promise<boolean> {
    const result = await this.client.set(key, value, {
      NX: true,
      expiration: { type: "EX", value: ttlSeconds },
    });
    return result !== null;
  }

  async del(...keys: string[]) {
    return keys.length === 0 ? 0 : this.client.del(keys);
  }

  async incr(key: string) {
    return this.client.incr(key);
  }

  async expire(key: string, seconds: number) {
    return this.client.expire(key, seconds);
  }

  async exists(key: string) {
    return this.client.exists(key);
  }

  async ping() {
    return this.client.ping();
  }
}

const socketOptions = {
  connectTimeout: 5000,
  reconnectStrategy: false as const,
};

const isTlsEnabled = env.REDIS_TLS_ENABLED === "true";

const buildRedisOptions = (): RedisClientOptions => {
  if (env.REDIS_URL) {
    return {
      url: env.REDIS_URL,
      socket: socketOptions,
    };
  }

  if (env.REDIS_HOST && env.REDIS_PORT && env.REDIS_PASSWORD) {
    return {
      username: env.REDIS_USERNAME ?? "default",
      password: env.REDIS_PASSWORD,
      socket: isTlsEnabled
        ? {
            host: env.REDIS_HOST,
            port: env.REDIS_PORT,
            tls: true,
            ...socketOptions,
          }
        : {
            host: env.REDIS_HOST,
            port: env.REDIS_PORT,
            ...socketOptions,
          },
    };
  }

  return {
    url: env.REDIS_URL!,
    socket: isTlsEnabled
      ? {
          tls: true,
          ...socketOptions,
        }
      : socketOptions,
  };
};

const client = createClient(buildRedisOptions());

export const redis = new RedisClientAdapter(client);

redis.on("error", (error: Error) => {
  logger.error({ error }, "Redis error");
});
