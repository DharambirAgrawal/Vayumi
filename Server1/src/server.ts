import { createServer } from "node:http";
import { app } from "./app.js";
import { appConfig } from "./core/config/app.js";
import { runDatabaseMigrations, verifyDatabaseConnection } from "./core/db/index.js";
import { redis } from "./core/redis/index.js";
import { logger } from "./core/utils/logger.js";
import { bootstrapCron } from "./modules/cron/cron.bootstrap.js";

const server = createServer(app);

const closeRedis = async () => {
  if (redis.status === "end" || redis.status === "wait") {
    return;
  }

  await redis.quit();
};

const shutdown = async (signal: string) => {
  logger.info({ signal }, "Shutting down server");
  server.close(async () => {
    await closeRedis();
    process.exit(0);
  });
};

process.on("SIGTERM", () => void shutdown("SIGTERM"));
process.on("SIGINT", () => void shutdown("SIGINT"));

const start = async () => {
  try {
    await verifyDatabaseConnection();
    await runDatabaseMigrations();
    await redis.connect();
    bootstrapCron();

    server.listen(appConfig.port, () => {
      logger.info({ port: appConfig.port }, "Server listening");
    });
  } catch (error) {
    logger.fatal({ error }, "Failed to start server");
    await closeRedis().catch(() => undefined);
    process.exit(1);
  }
};

await start();
