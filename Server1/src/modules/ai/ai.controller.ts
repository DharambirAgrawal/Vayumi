import type { NextFunction, Request, Response } from "express";
import { AuthError } from "../../core/errors/index.js";
import { aiService } from "./ai.service.js";
import type { ChatRequestInput } from "./ai.validators.js";

const asyncHandler =
  (handler: (req: Request, res: Response) => Promise<void>) =>
  (req: Request, res: Response, next: NextFunction) => {
    handler(req, res).catch(next);
  };

const requireUser = (req: Request) => {
  if (!req.auth) {
    throw new AuthError("Authentication required");
  }
  return req.auth.user;
};

export const aiController = {
  status: asyncHandler(async (req, res) => {
    requireUser(req);
    res.json(aiService.status());
  }),

  chat: asyncHandler(async (req, res) => {
    requireUser(req);
    const { body, provider } = await aiService.chat(req.body as ChatRequestInput);
    res.setHeader("X-AI-Provider", provider);
    res.json(body);
  }),
};
