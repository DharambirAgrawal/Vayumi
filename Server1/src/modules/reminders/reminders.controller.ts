import type { NextFunction, Request, Response } from "express";
import { AuthError, ValidationError } from "../../core/errors/index.js";
import { remindersService } from "./reminders.service.js";
import type {
  CreateReminderInput,
  ListRemindersQuery,
  SnoozeReminderInput,
  UpcomingRemindersQuery,
  UpdateReminderInput,
} from "./reminders.validators.js";

const asyncHandler =
  (handler: (req: Request, res: Response) => Promise<void>) =>
  (req: Request, res: Response, next: NextFunction) => {
    handler(req, res).catch(next);
  };

const resolveUserId = (req: Request, bodyUserId?: string): string => {
  if (req.internalService) {
    if (!bodyUserId) {
      throw new ValidationError("user_id is required for service requests");
    }
    return bodyUserId;
  }

  if (!req.auth) {
    throw new AuthError("Authentication required");
  }

  return req.auth.user.id;
};

export const remindersController = {
  create: asyncHandler(async (req, res) => {
    const input = req.body as CreateReminderInput;
    const userId = resolveUserId(req, input.user_id);
    const source = req.internalService ? "agent" : "user";
    const result = await remindersService.createReminder(userId, input, source);
    res.status(201).json(result);
  }),

  list: asyncHandler(async (req, res) => {
    const userId = resolveUserId(req);
    const result = await remindersService.listReminders(userId, req.query as unknown as ListRemindersQuery);
    res.json(result);
  }),

  upcoming: asyncHandler(async (req, res) => {
    const userId = resolveUserId(req);
    const result = await remindersService.listUpcoming(userId, req.query as unknown as UpcomingRemindersQuery);
    res.json(result);
  }),

  getById: asyncHandler(async (req, res) => {
    const userId = resolveUserId(req);
    const { id } = req.params as { id: string };
    const result = await remindersService.getReminder(userId, id);
    res.json(result);
  }),

  update: asyncHandler(async (req, res) => {
    const userId = resolveUserId(req);
    const { id } = req.params as { id: string };
    const result = await remindersService.updateReminder(userId, id, req.body as UpdateReminderInput);
    res.json(result);
  }),

  remove: asyncHandler(async (req, res) => {
    const userId = resolveUserId(req);
    const { id } = req.params as { id: string };
    const result = await remindersService.deleteReminder(userId, id);
    res.json(result);
  }),

  snooze: asyncHandler(async (req, res) => {
    const userId = resolveUserId(req);
    const { id } = req.params as { id: string };
    const result = await remindersService.snoozeReminder(userId, id, req.body as SnoozeReminderInput);
    res.json(result);
  }),

  cancel: asyncHandler(async (req, res) => {
    const userId = resolveUserId(req);
    const { id } = req.params as { id: string };
    const result = await remindersService.cancelReminder(userId, id);
    res.json(result);
  }),

  fireInternal: asyncHandler(async (_req, res) => {
    const result = await remindersService.fireRemindersNow();
    res.json(result);
  }),
};
