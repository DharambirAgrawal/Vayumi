import { Router } from "express";
import { authenticate } from "../../core/middleware/authenticate.js";
import { integrationsController } from "./integrations.controller.js";
import { gmailRouter } from "./gmail/gmail.router.js";
import { outlookRouter } from "./outlook/outlook.router.js";

export const integrationsRouter = Router();

integrationsRouter.get("/", authenticate, integrationsController.list);
integrationsRouter.use("/gmail", gmailRouter);
integrationsRouter.use("/outlook", outlookRouter);
