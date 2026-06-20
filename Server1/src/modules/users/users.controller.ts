import type { NextFunction, Request, Response } from "express";
import { AuthError } from "../../core/errors/index.js";
import { usersService } from "./users.service.js";
import type { UpdateProfileInput } from "./users.validators.js";

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

export const usersController = {
  getProfile: asyncHandler(async (req, res) => {
    const { user } = requireAuth(req);
    res.json(await usersService.getProfile(user.id));
  }),

  updateProfile: asyncHandler(async (req, res) => {
    const { user } = requireAuth(req);
    res.json(await usersService.updateProfile(user.id, req.body as UpdateProfileInput));
  }),

  uploadAvatar: asyncHandler(async (req, res) => {
    const { user } = requireAuth(req);
    res.json(await usersService.uploadAvatar(user.id, req.file));
  }),

  deleteAccount: asyncHandler(async (req, res) => {
    const { user } = requireAuth(req);
    res.json(await usersService.deleteAccount(user.id));
  }),
};
