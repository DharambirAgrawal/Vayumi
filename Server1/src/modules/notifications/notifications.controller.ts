import type { NextFunction, Request, Response } from "express";
import { AuthError } from "../../core/errors/index.js";
import { notificationsService } from "./notifications.service.js";
import type { RegisterPushTokenInput, RemovePushTokenInput } from "./notifications.validators.js";

const asyncHandler =
  (handler: (req: Request, res: Response) => Promise<void>) =>
  (req: Request, res: Response, next: NextFunction) => {
    handler(req, res).catch(next);
  };

const requireAuth = (req: Request) => {
  if (!req.auth) {
    throw new AuthError();
  }
  return req.auth;
};

export const notificationsController = {
  registerPushToken: asyncHandler(async (req, res) => {
    const { user, session } = requireAuth(req);
    res.status(201).json(
      await notificationsService.registerPushToken(user.id, session.id, req.body as RegisterPushTokenInput),
    );
  }),

  removePushToken: asyncHandler(async (req, res) => {
    const { user } = requireAuth(req);
    res.json(await notificationsService.removePushToken(user.id, req.body as RemovePushTokenInput));
  }),
};
