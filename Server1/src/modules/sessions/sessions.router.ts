import { Router } from "express";
import { z } from "zod";
import { authenticate } from "../../core/middleware/authenticate.js";
import { validate } from "../../core/middleware/validate.js";
import { sessionsController } from "./sessions.controller.js";

export const sessionsRouter = Router();

const sessionIdSchema = z.object({
  sessionId: z.string().uuid(),
});

sessionsRouter.use(authenticate);
sessionsRouter.get("/", sessionsController.list);
sessionsRouter.delete("/:sessionId", validate.params(sessionIdSchema), sessionsController.revoke);
