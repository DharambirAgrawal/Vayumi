import { Router } from "express";
import { authenticate } from "../../core/middleware/authenticate.js";
import { validate } from "../../core/middleware/validate.js";
import { lifeController } from "./life.controller.js";
import {
  listLifeEntriesQuerySchema,
  listLifeTabsQuerySchema,
  syncPullQuerySchema,
  syncPushSchema,
  upsertLifeEntrySchema,
  upsertLifeTabSchema,
} from "./life.validators.js";

export const lifeRouter = Router();

// Bulk sync (offline-first device round-trips): pull changed-since, push a batch.
lifeRouter.get("/sync", authenticate, validate.query(syncPullQuerySchema), lifeController.syncPull);
lifeRouter.post("/sync", authenticate, validate.body(syncPushSchema), lifeController.syncPush);

// Granular REST (single tracker / entry) for the agent, web, and fine-grained edits.
lifeRouter.get("/tabs", authenticate, validate.query(listLifeTabsQuerySchema), lifeController.listTabs);
lifeRouter.post("/tabs", authenticate, validate.body(upsertLifeTabSchema), lifeController.upsertTab);
lifeRouter.delete("/tabs/:id", authenticate, lifeController.deleteTab);

lifeRouter.get(
  "/entries",
  authenticate,
  validate.query(listLifeEntriesQuerySchema),
  lifeController.listEntries,
);
lifeRouter.post(
  "/entries",
  authenticate,
  validate.body(upsertLifeEntrySchema),
  lifeController.upsertEntry,
);
lifeRouter.delete("/entries/:id", authenticate, lifeController.deleteEntry);
