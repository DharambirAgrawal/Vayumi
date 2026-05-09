import type { NextFunction, Request, Response } from "express";
import { AuthError } from "../../core/errors/index.js";
import { sessionsService } from "./sessions.service.js";

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

export const sessionsController = {
  list: asyncHandler(async (req, res) => {
    const { user, session } = requireAuth(req);
    res.json(await sessionsService.list(user.id, session.id));
  }),

  revoke: asyncHandler(async (req, res) => {
    const { user, session } = requireAuth(req);
    const { sessionId } = req.params as { sessionId: string };
    res.json(await sessionsService.revoke(user.id, sessionId, session.id));
  }),
};
