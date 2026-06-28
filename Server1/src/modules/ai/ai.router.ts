import { Router } from "express";
import type { NextFunction, Request, Response } from "express";
import { authenticate } from "../../core/middleware/authenticate.js";
import { rateLimiter } from "../../core/middleware/rateLimiter.js";
import { validate } from "../../core/middleware/validate.js";
import { appConfig } from "../../core/config/app.js";
import { AppError } from "../../core/errors/index.js";
import { aiController } from "./ai.controller.js";
import { chatRequestSchema } from "./ai.validators.js";

const { ai: aiLimits } = appConfig.limits;

// Per-user quotas (not per-IP) — one tool-loop round = one request.
const perUser = (req: Request) => req.auth?.user.id ?? req.ip ?? "anon";

// Optional hard allowlist: when AI_CLOUD_ALLOWED_EMAILS is set, only those accounts
// may use the cloud AI (lock it to yourself). Empty = any authenticated user.
const allowlist = (req: Request, _res: Response, next: NextFunction) => {
  if (aiLimits.allowedEmails.length === 0) return next();
  const email = req.auth?.user.email?.toLowerCase();
  if (email && aiLimits.allowedEmails.includes(email)) return next();
  next(new AppError(403, "AI_FORBIDDEN", "Cloud AI is not enabled for this account."));
};

const minuteLimit = rateLimiter({
  windowSeconds: 60,
  max: aiLimits.minuteLimit,
  keyPrefix: "ai-cloud-min",
  keyBy: perUser,
});

const dailyLimit = rateLimiter({
  windowSeconds: 24 * 60 * 60,
  max: aiLimits.dailyLimit,
  keyPrefix: "ai-cloud-day",
  keyBy: perUser,
});

export const aiRouter = Router();

// Cloud LLM proxy for the app's "Server" mode. Authorized users only; keys stay
// server-side; per-user daily + per-minute caps; provider fallback in the service.
aiRouter.get("/status", authenticate, allowlist, aiController.status);

aiRouter.post(
  "/chat",
  authenticate,
  allowlist,
  minuteLimit,
  dailyLimit,
  validate.body(chatRequestSchema),
  aiController.chat,
);
