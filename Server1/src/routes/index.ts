import { Router } from "express";
import { authRouter } from "../modules/auth/auth.router.js";
import { notificationsRouter } from "../modules/notifications/notifications.router.js";
import { sessionsRouter } from "../modules/sessions/sessions.router.js";
import { settingsRouter } from "../modules/settings/settings.router.js";
import { usersRouter } from "../modules/users/users.router.js";
import { integrationsRouter } from "../modules/integrations/integrations.router.js";
import { meetingsRouter } from "../modules/meetings/meetings.router.js";
import {
  internalRemindersRouter,
  remindersRouter,
} from "../modules/reminders/reminders.router.js";

export const apiRouter = Router();
export const internalRouter = Router();

apiRouter.get("/health", (_req, res) => {
  res.json({ status: "ok" });
});

apiRouter.use("/auth", authRouter);
apiRouter.use("/sessions", sessionsRouter);
apiRouter.use("/notifications", notificationsRouter);
apiRouter.use("/users", usersRouter);
apiRouter.use("/settings", settingsRouter);
apiRouter.use("/integrations", integrationsRouter);
apiRouter.use("/reminders", remindersRouter);
apiRouter.use("/meetings", meetingsRouter);

internalRouter.use(internalRemindersRouter);
