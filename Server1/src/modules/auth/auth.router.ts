import { Router } from "express";
import { appConfig } from "../../core/config/app.js";
import { authenticate } from "../../core/middleware/authenticate.js";
import { rateLimiter } from "../../core/middleware/rateLimiter.js";
import { validate } from "../../core/middleware/validate.js";
import { authController } from "./auth.controller.js";
import {
  changePasswordSchema,
  forgotPasswordSchema,
  googleSchema,
  loginSchema,
  refreshSchema,
  registerSchema,
  resendVerificationSchema,
  resetPasswordSchema,
  tokenQuerySchema,
} from "./auth.validators.js";

export const authRouter = Router();

const authLimit = rateLimiter({ ...appConfig.rateLimit.auth, keyPrefix: "auth" });

authRouter.post("/register", validate.body(registerSchema), authController.register);
authRouter.post("/login", authLimit, validate.body(loginSchema), authController.login);
authRouter.post("/google", authLimit, validate.body(googleSchema), authController.google);
authRouter.get("/verify-email", validate.query(tokenQuerySchema), authController.verifyEmail);
authRouter.post("/verify-email/resend", authenticate, authController.resendVerification);
authRouter.post("/verify-email/resend/request", authLimit, validate.body(resendVerificationSchema), authController.resendVerificationByEmail);
authRouter.post("/token/refresh", authLimit, validate.body(refreshSchema), authController.refresh);
authRouter.post("/logout", authenticate, authController.logout);
authRouter.post("/logout/all", authenticate, authController.logoutAll);
authRouter.post("/password/forgot", authLimit, validate.body(forgotPasswordSchema), authController.forgotPassword);
authRouter.post("/password/reset", validate.body(resetPasswordSchema), authController.resetPassword);
authRouter.post("/password/change", authenticate, validate.body(changePasswordSchema), authController.changePassword);
authRouter.get("/me", authenticate, authController.me);
