import { Router } from "express";
import { authRouter } from "../modules/auth/auth.router.js";
import { notificationsRouter } from "../modules/notifications/notifications.router.js";
import { sessionsRouter } from "../modules/sessions/sessions.router.js";

export const apiRouter = Router();

apiRouter.get("/health", (_req, res) => {
  res.json({ status: "ok" });
});

apiRouter.use("/auth", authRouter);
apiRouter.use("/sessions", sessionsRouter);
apiRouter.use("/notifications", notificationsRouter);
