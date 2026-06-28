import type { ErrorRequestHandler } from "express";
import { MulterError } from "multer";
import { ZodError } from "zod";
import { AppError, ValidationError } from "../errors/index.js";
import { logger } from "../utils/logger.js";

const fromMulterError = (error: MulterError) =>
  error.code === "LIMIT_FILE_SIZE"
    ? new AppError(413, "FILE_TOO_LARGE", "The file is too large.")
    : new AppError(400, "UPLOAD_ERROR", error.message);

export const errorHandler: ErrorRequestHandler = (error, _req, res, _next) => {
  const appError =
    error instanceof ZodError
      ? new ValidationError("Validation failed", error.flatten())
      : error instanceof MulterError
        ? fromMulterError(error)
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
