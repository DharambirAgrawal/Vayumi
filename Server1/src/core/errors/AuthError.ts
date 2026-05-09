import { AppError } from "./AppError.js";

export class AuthError extends AppError {
  constructor(message = "Unauthorized", code = "AUTH_ERROR", statusCode = 401) {
    super(statusCode, code, message);
  }
}

export class ForbiddenError extends AppError {
  constructor(message = "Forbidden", code = "FORBIDDEN") {
    super(403, code, message);
  }
}
