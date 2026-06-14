import cron from "node-cron";
import { logger } from "../../core/utils/logger.js";
import { cleanExpiredTokensJob } from "./jobs/cleanExpiredTokens.js";
import { fireRemindersJob } from "./jobs/fireReminders.js";

const jobs = [cleanExpiredTokensJob, fireRemindersJob];

export const bootstrapCron = () => {
  for (const job of jobs) {
    cron.schedule(job.schedule, () => {
      job.run().catch((error) => {
        logger.error({ error, job: job.name }, "Cron job failed");
      });
    });

    logger.info({ job: job.name, schedule: job.schedule }, "Cron job registered");
  }
};
