import type { NextFunction, Request, Response } from "express";
import { AuthError } from "../../core/errors/index.js";
import { settingsService } from "./settings.service.js";
import type { SettingsPatchInput } from "./settings.validators.js";

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

export const settingsController = {
  getSettings: asyncHandler(async (req, res) => {
    const { user } = requireAuth(req);
    res.json(await settingsService.getSettings(user.id));
  }),

  updateNotifications: asyncHandler(async (req, res) => {
    const { user } = requireAuth(req);
    res.json(await settingsService.updateNotifications(user.id, req.body as SettingsPatchInput));
  }),

  updatePrivacy: asyncHandler(async (req, res) => {
    const { user } = requireAuth(req);
    res.json(await settingsService.updatePrivacy(user.id, req.body as SettingsPatchInput));
  }),

  updateAppearance: asyncHandler(async (req, res) => {
    const { user } = requireAuth(req);
    res.json(await settingsService.updateAppearance(user.id, req.body as SettingsPatchInput));
  }),
};
