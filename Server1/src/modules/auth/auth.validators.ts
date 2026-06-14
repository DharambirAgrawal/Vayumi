import { z } from "zod";
import { deviceTypes } from "../../core/types/index.js";

const deviceSchema = z.object({
  device_type: z.enum(deviceTypes).default("web"),
  device_name: z.string().trim().min(1).max(100).optional(),
  device_fingerprint: z.string().trim().min(1).max(255).optional(),
});

export const registerSchema = deviceSchema.extend({
  email: z.string().trim().email().transform((value) => value.toLowerCase()),
  password: z.string().min(8).max(128),
  name: z.string().trim().min(1).max(100).optional(),
});

export const loginSchema = deviceSchema.extend({
  email: z.string().trim().email().transform((value) => value.toLowerCase()),
  password: z.string().min(1),
});

export const googleSchema = deviceSchema.extend({
  id_token: z.string().min(1),
});

export const refreshSchema = z.object({
  refresh_token: z.string().min(1),
});

export const verifyEmailCodeSchema = z.object({
  code: z.string().trim().regex(/^\d{6}$/, "Code must be 6 digits"),
});

export const verifyEmailCodeByEmailSchema = z.object({
  email: z.string().trim().email().transform((value) => value.toLowerCase()),
  code: z.string().trim().regex(/^\d{6}$/, "Code must be 6 digits"),
});

export const forgotPasswordSchema = z.object({
  email: z.string().trim().email().transform((value) => value.toLowerCase()),
});

export const resendVerificationSchema = z.object({
  email: z.string().trim().email().transform((value) => value.toLowerCase()),
});

export const resetPasswordSchema = z.object({
  token: z.string().min(1),
  new_password: z.string().min(8).max(128),
});

export const changePasswordSchema = z.object({
  current_password: z.string().min(1),
  new_password: z.string().min(8).max(128),
});

export type RegisterInput = z.infer<typeof registerSchema>;
export type LoginInput = z.infer<typeof loginSchema>;
export type GoogleInput = z.infer<typeof googleSchema>;
export type RefreshInput = z.infer<typeof refreshSchema>;
export type VerifyEmailCodeInput = z.infer<typeof verifyEmailCodeSchema>;
export type VerifyEmailCodeByEmailInput = z.infer<typeof verifyEmailCodeByEmailSchema>;
export type ForgotPasswordInput = z.infer<typeof forgotPasswordSchema>;
export type ResendVerificationInput = z.infer<typeof resendVerificationSchema>;
export type ResetPasswordInput = z.infer<typeof resetPasswordSchema>;
export type ChangePasswordInput = z.infer<typeof changePasswordSchema>;
