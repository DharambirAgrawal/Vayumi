import { Router } from "express";
import { authenticate } from "../../core/middleware/authenticate.js";
import { validate } from "../../core/middleware/validate.js";
import { settingsController } from "./settings.controller.js";
import {
  updateAppearanceSchema,
  updateNotificationsSchema,
  updatePrivacySchema,
} from "./settings.validators.js";

export const settingsRouter = Router();

settingsRouter.use(authenticate);
settingsRouter.get("/", settingsController.getSettings);
settingsRouter.patch("/notifications", validate.body(updateNotificationsSchema), settingsController.updateNotifications);
settingsRouter.patch("/privacy", validate.body(updatePrivacySchema), settingsController.updatePrivacy);
settingsRouter.patch("/appearance", validate.body(updateAppearanceSchema), settingsController.updateAppearance);
