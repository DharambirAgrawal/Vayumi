import type { NextFunction, Request, Response } from "express";
import { AuthError } from "../../core/errors/index.js";
import { memoryService } from "./memory.service.js";
import type { SyncPullQuery, SyncPushInput } from "./memory.validators.js";

const asyncHandler =
  (handler: (req: Request, res: Response) => Promise<void>) =>
  (req: Request, res: Response, next: NextFunction) => {
    handler(req, res).catch(next);
  };

const requireUserId = (req: Request): string => {
  if (!req.auth) {
    throw new AuthError("Authentication required");
  }
  return req.auth.user.id;
};

export const memoryController = {
  syncPull: asyncHandler(async (req, res) => {
    const userId = requireUserId(req);
    const result = await memoryService.syncPull(userId, req.query as unknown as SyncPullQuery);
    res.json(result);
  }),

  syncPush: asyncHandler(async (req, res) => {
    const userId = requireUserId(req);
    const result = await memoryService.syncPush(userId, req.body as SyncPushInput);
    res.json(result);
  }),
};
