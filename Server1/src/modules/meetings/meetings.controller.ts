import type { NextFunction, Request, Response } from "express";
import { AuthError } from "../../core/errors/index.js";
import { meetingsService } from "./meetings.service.js";
import type {
  ListMeetingsQuery,
  UpdateMeetingInput,
  UpsertMeetingInput,
} from "./meetings.validators.js";

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

export const meetingsController = {
  upsert: asyncHandler(async (req, res) => {
    const userId = requireUserId(req);
    const result = await meetingsService.upsertMeeting(userId, req.body as UpsertMeetingInput);
    res.json(result);
  }),

  list: asyncHandler(async (req, res) => {
    const userId = requireUserId(req);
    const result = await meetingsService.listMeetings(
      userId,
      req.query as unknown as ListMeetingsQuery,
    );
    res.json(result);
  }),

  getById: asyncHandler(async (req, res) => {
    const userId = requireUserId(req);
    const { id } = req.params as { id: string };
    const result = await meetingsService.getMeeting(userId, id);
    res.json(result);
  }),

  update: asyncHandler(async (req, res) => {
    const userId = requireUserId(req);
    const { id } = req.params as { id: string };
    const result = await meetingsService.updateMeeting(userId, id, req.body as UpdateMeetingInput);
    res.json(result);
  }),

  remove: asyncHandler(async (req, res) => {
    const userId = requireUserId(req);
    const { id } = req.params as { id: string };
    const result = await meetingsService.deleteMeeting(userId, id);
    res.json(result);
  }),
};
