import type { NextFunction, Request, Response } from "express";
import { AuthError } from "../../core/errors/index.js";
import { authService } from "./auth.service.js";
import type {
  ChangePasswordInput,
  ForgotPasswordInput,
  GoogleInput,
  LoginInput,
  RefreshInput,
  RegisterInput,
  ResendVerificationInput,
  ResetPasswordInput,
} from "./auth.validators.js";

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

export const authController = {
  register: asyncHandler(async (req, res) => {
    res.status(201).json(await authService.register(req.body as RegisterInput));
  }),

  login: asyncHandler(async (req, res) => {
    res.json(await authService.login(req.body as LoginInput));
  }),

  google: asyncHandler(async (req, res) => {
    res.json(await authService.google(req.body as GoogleInput));
  }),

  verifyEmail: asyncHandler(async (req, res) => {
    res.json(await authService.verifyEmail(String(req.query.token)));
  }),

  resendVerification: asyncHandler(async (req, res) => {
    const { user } = requireAuth(req);
    res.json(await authService.resendVerification(user));
  }),

  resendVerificationByEmail: asyncHandler(async (req, res) => {
    res.json(await authService.resendVerificationByEmail(req.body as ResendVerificationInput));
  }),

  refresh: asyncHandler(async (req, res) => {
    res.json(await authService.refresh(req.body as RefreshInput));
  }),

  logout: asyncHandler(async (req, res) => {
    const { user, session, token } = requireAuth(req);
    res.json(await authService.logout(user.id, session.id, token));
  }),

  logoutAll: asyncHandler(async (req, res) => {
    const { user, token } = requireAuth(req);
    res.json(await authService.logoutAll(user.id, token));
  }),

  forgotPassword: asyncHandler(async (req, res) => {
    res.json(await authService.forgotPassword(req.body as ForgotPasswordInput));
  }),

  resetPassword: asyncHandler(async (req, res) => {
    res.json(await authService.resetPassword(req.body as ResetPasswordInput));
  }),

  changePassword: asyncHandler(async (req, res) => {
    const { user } = requireAuth(req);
    res.json(await authService.changePassword(user, req.body as ChangePasswordInput));
  }),

  me: asyncHandler(async (req, res) => {
    const { user } = requireAuth(req);
    res.json(await authService.me(user));
  }),
};
