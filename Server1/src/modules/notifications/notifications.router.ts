import { Router } from "express";
import { authenticate } from "../../core/middleware/authenticate.js";
import { validate } from "../../core/middleware/validate.js";
import { notificationsController } from "./notifications.controller.js";
import { registerPushTokenSchema, removePushTokenSchema } from "./notifications.validators.js";

export const notificationsRouter = Router();

notificationsRouter.use(authenticate);
notificationsRouter.post("/push-token", validate.body(registerPushTokenSchema), notificationsController.registerPushToken);
notificationsRouter.delete("/push-token", validate.body(removePushTokenSchema), notificationsController.removePushToken);
