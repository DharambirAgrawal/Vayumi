import { remindersService } from "../../reminders/reminders.service.js";
import type { CronJobDefinition } from "../cron.types.js";

export const fireRemindersJob: CronJobDefinition = {
  name: "fireReminders",
  schedule: "* * * * *",
  run: async () => {
    await remindersService.fireRemindersNow();
  },
};
