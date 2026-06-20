/**
 * Token / code lifetimes in seconds. These back database `expires_at` columns
 * and cooldown windows — they are not tied to any cache backend.
 */
export const TokenLifetimes = {
  refreshTokenSeconds: 90 * 24 * 60 * 60,
  passwordResetSeconds: 15 * 60,
  emailVerificationCodeSeconds: 10 * 60,
  emailVerificationCooldownSeconds: 60,
} as const;
