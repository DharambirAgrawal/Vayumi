import { Router } from "express";
import { authenticate } from "../../core/middleware/authenticate.js";
import { validate } from "../../core/middleware/validate.js";
import { memoryController } from "./memory.controller.js";
import { syncPullQuerySchema, syncPushSchema } from "./memory.validators.js";

export const memoryRouter = Router();

// Curated long-term facts — bulk sync (the set is tiny, capped ~50 on-device).
memoryRouter.get("/sync", authenticate, validate.query(syncPullQuerySchema), memoryController.syncPull);
memoryRouter.post("/sync", authenticate, validate.body(syncPushSchema), memoryController.syncPush);
