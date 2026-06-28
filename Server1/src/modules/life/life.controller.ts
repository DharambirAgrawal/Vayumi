import type { NextFunction, Request, Response } from "express";
import { AuthError } from "../../core/errors/index.js";
import { lifeService } from "./life.service.js";
import type {
  ListLifeEntriesQuery,
  ListLifeTabsQuery,
  SyncPullQuery,
  SyncPushInput,
  UpsertLifeEntryInput,
  UpsertLifeTabInput,
} from "./life.validators.js";

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

export const lifeController = {
  upsertTab: asyncHandler(async (req, res) => {
    const userId = requireUserId(req);
    const result = await lifeService.upsertTab(userId, req.body as UpsertLifeTabInput);
    res.json(result);
  }),

  listTabs: asyncHandler(async (req, res) => {
    const userId = requireUserId(req);
    const result = await lifeService.listTabs(userId, req.query as unknown as ListLifeTabsQuery);
    res.json(result);
  }),

  deleteTab: asyncHandler(async (req, res) => {
    const userId = requireUserId(req);
    const { id } = req.params as { id: string };
    const result = await lifeService.deleteTab(userId, id);
    res.json(result);
  }),

  upsertEntry: asyncHandler(async (req, res) => {
    const userId = requireUserId(req);
    const result = await lifeService.upsertEntry(userId, req.body as UpsertLifeEntryInput);
    res.json(result);
  }),

  listEntries: asyncHandler(async (req, res) => {
    const userId = requireUserId(req);
    const result = await lifeService.listEntries(
      userId,
      req.query as unknown as ListLifeEntriesQuery,
    );
    res.json(result);
  }),

  deleteEntry: asyncHandler(async (req, res) => {
    const userId = requireUserId(req);
    const { id } = req.params as { id: string };
    const result = await lifeService.deleteEntry(userId, id);
    res.json(result);
  }),

  syncPull: asyncHandler(async (req, res) => {
    const userId = requireUserId(req);
    const result = await lifeService.syncPull(userId, req.query as unknown as SyncPullQuery);
    res.json(result);
  }),

  syncPush: asyncHandler(async (req, res) => {
    const userId = requireUserId(req);
    const result = await lifeService.syncPush(userId, req.body as SyncPushInput);
    res.json(result);
  }),
};
