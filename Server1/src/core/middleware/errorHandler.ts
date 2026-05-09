import type { ErrorRequestHandler } from "express";
import { ZodError } from "zod";
import { AppError, ValidationError } from "../errors/index.js";
import { logger } from "../utils/logger.js";

export const errorHandler: ErrorRequestHandler = (error, _req, res, _next) => {
  const appError =
    error instanceof ZodError
      ? new ValidationError("Validation failed", error.flatten())
      : error instanceof AppError
        ? error
        : new AppError(500, "INTERNAL_SERVER_ERROR", "Internal server error");

  if (appError.statusCode >= 500) {
    logger.error({ err: error }, appError.message);
  }

  res.status(appError.statusCode).json({
    error: {
      code: appError.code,
      message: appError.message,
      details: appError.details,
    },
  });
};
