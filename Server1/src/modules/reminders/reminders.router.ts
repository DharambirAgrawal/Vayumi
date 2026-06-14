import { Router } from "express";
import { authenticate } from "../../core/middleware/authenticate.js";
import { authenticateUserOrService } from "../../core/middleware/authenticateUserOrService.js";
import { validate } from "../../core/middleware/validate.js";
import { verifyInternalReminderSecret } from "../../core/middleware/verifyInternalReminderSecret.js";
import { remindersController } from "./reminders.controller.js";
import {
  createReminderSchema,
  listRemindersQuerySchema,
  snoozeReminderSchema,
  upcomingRemindersQuerySchema,
  updateReminderSchema,
} from "./reminders.validators.js";

export const remindersRouter = Router();

remindersRouter.get(
  "/upcoming",
  authenticate,
  validate.query(upcomingRemindersQuerySchema),
  remindersController.upcoming,
);

remindersRouter.get(
  "/",
  authenticate,
  validate.query(listRemindersQuerySchema),
  remindersController.list,
);

remindersRouter.get("/:id", authenticate, remindersController.getById);

remindersRouter.post(
  "/",
  authenticateUserOrService,
  validate.body(createReminderSchema),
  remindersController.create,
);

remindersRouter.patch(
  "/:id",
  authenticateUserOrService,
  validate.body(updateReminderSchema),
  remindersController.update,
);

remindersRouter.delete("/:id", authenticateUserOrService, remindersController.remove);

remindersRouter.post(
  "/:id/snooze",
  authenticate,
  validate.body(snoozeReminderSchema),
  remindersController.snooze,
);

remindersRouter.post("/:id/cancel", authenticateUserOrService, remindersController.cancel);

export const internalRemindersRouter = Router();

internalRemindersRouter.post(
  "/reminders/fire",
  verifyInternalReminderSecret,
  remindersController.fireInternal,
);
