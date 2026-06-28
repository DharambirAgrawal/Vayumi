import { Router } from "express";
import multer from "multer";
import { appConfig } from "../../core/config/app.js";
import { authenticate } from "../../core/middleware/authenticate.js";
import { validate } from "../../core/middleware/validate.js";
import { usersController } from "./users.controller.js";
import { updateProfileSchema } from "./users.validators.js";

export const usersRouter = Router();

// Bound the upload at the streaming layer so an oversized file is rejected
// BEFORE it's buffered into memory (the service-level size check is a backstop).
const upload = multer({
  storage: multer.memoryStorage(),
  limits: { fileSize: appConfig.limits.upload.avatarMaxBytes, files: 1 },
});

usersRouter.use(authenticate);
usersRouter.get("/profile", usersController.getProfile);
usersRouter.patch("/profile", validate.body(updateProfileSchema), usersController.updateProfile);
usersRouter.post("/avatar", upload.single("avatar"), usersController.uploadAvatar);
usersRouter.delete("/account", usersController.deleteAccount);
