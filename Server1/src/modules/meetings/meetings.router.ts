import { Router } from "express";
import { authenticate } from "../../core/middleware/authenticate.js";
import { validate } from "../../core/middleware/validate.js";
import { meetingsController } from "./meetings.controller.js";
import {
  listMeetingsQuerySchema,
  updateMeetingSchema,
  upsertMeetingSchema,
} from "./meetings.validators.js";

export const meetingsRouter = Router();

meetingsRouter.get(
  "/",
  authenticate,
  validate.query(listMeetingsQuerySchema),
  meetingsController.list,
);

meetingsRouter.get("/:id", authenticate, meetingsController.getById);

meetingsRouter.post(
  "/",
  authenticate,
  validate.body(upsertMeetingSchema),
  meetingsController.upsert,
);

meetingsRouter.patch(
  "/:id",
  authenticate,
  validate.body(updateMeetingSchema),
  meetingsController.update,
);

meetingsRouter.delete("/:id", authenticate, meetingsController.remove);
