import type { NextFunction, Request, Response } from "express";
import { AuthError } from "../../core/errors/index.js";
import { integrationsService } from "./integrations.service.js";

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

export const integrationsController = {
  list: asyncHandler(async (req, res) => {
    const { user } = requireAuth(req);
    res.json({ integrations: await integrationsService.listForUser(user.id) });
  }),
};
