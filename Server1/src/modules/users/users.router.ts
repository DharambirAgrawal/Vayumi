import { Router } from "express";
import multer from "multer";
import { authenticate } from "../../core/middleware/authenticate.js";
import { validate } from "../../core/middleware/validate.js";
import { usersController } from "./users.controller.js";
import { updateProfileSchema } from "./users.validators.js";

export const usersRouter = Router();

const upload = multer({ storage: multer.memoryStorage() });

usersRouter.use(authenticate);
usersRouter.get("/profile", usersController.getProfile);
usersRouter.patch("/profile", validate.body(updateProfileSchema), usersController.updateProfile);
usersRouter.post("/avatar", upload.single("avatar"), usersController.uploadAvatar);
usersRouter.delete("/account", usersController.deleteAccount);
