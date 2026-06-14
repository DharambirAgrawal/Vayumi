import { timingSafeEqual } from "node:crypto";
import type { NextFunction, Request, Response } from "express";
import { remindersConfig } from "../config/reminders.js";
import { AuthError } from "../errors/index.js";

const safeCompare = (provided: string, expected: string): boolean => {
  const providedBuffer = Buffer.from(provided);
  const expectedBuffer = Buffer.from(expected);

  if (providedBuffer.length !== expectedBuffer.length) {
    return false;
  }

  return timingSafeEqual(providedBuffer, expectedBuffer);
};

export const verifyInternalReminderSecret = (req: Request, _res: Response, next: NextFunction) => {
  const provided = req.header("x-internal-secret");

  if (!provided || !safeCompare(provided, remindersConfig.internalReminderSecret)) {
    next(new AuthError("Invalid internal secret"));
    return;
  }

  next();
};
