import { OAuth2Client, type LoginTicket } from "google-auth-library";
import { and, eq, gt, isNull } from "drizzle-orm";
import mailchecker from "mailchecker";
import nodemailer from "nodemailer";
import { appConfig } from "../../core/config/app.js";
import { env } from "../../core/config/index.js";
import { db } from "../../core/db/index.js";
import {
  emailVerifications,
  passwordResetTokens,
  sessions,
  userSettings,
  userIdentities,
  users,
} from "../../core/db/schema/index.js";
import { AppError, AuthError, NotFoundError } from "../../core/errors/index.js";
import { cache } from "../../core/redis/helpers.js";
import { redis } from "../../core/redis/index.js";
import { RedisKeys, RedisTTL } from "../../core/redis/keys.js";
import { addSeconds } from "../../core/utils/date.js";
import { compareHash, hashPassword, randomToken, sha256 } from "../../core/utils/crypto.js";
import type { AccessTokenPayload, User } from "../../core/types/index.js";
import { logger } from "../../core/utils/logger.js";
import {
  createRefreshToken,
  createSessionPayload,
  issueTokenPair,
  parseRefreshToken,
} from "./auth.helpers.js";
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

const googleClient = new OAuth2Client();
const googleAudiences = env.GOOGLE_CLIENT_ID
  .split(",")
  .map((value) => value.trim())
  .filter(Boolean);

const mailer = nodemailer.createTransport({
  host: env.SMTP_HOST,
  port: env.SMTP_PORT,
  secure: env.SMTP_PORT === 465,
  auth: {
    user: env.SMTP_USER,
    pass: env.SMTP_PASS,
  },
});

const publicUser = (user: User) => ({
  id: user.id,
  email: user.email,
  name: user.name,
  avatar_url: user.avatarUrl,
  is_verified: user.isVerified,
  created_at: user.createdAt,
  updated_at: user.updatedAt,
});

const sendEmail = async (input: { to: string; subject: string; text: string }) => {
  await mailer.sendMail({
    from: env.FROM_EMAIL,
    to: input.to,
    subject: input.subject,
    text: input.text,
  });
};

const trySendVerificationEmail = async (user: User) => {
  try {
    await sendVerificationEmail(user);
    return true;
  } catch (error) {
    logger.error({ err: error, userId: user.id, email: user.email }, "Failed to send verification email");
    return false;
  }
};

const trySendPasswordResetEmail = async (user: User) => {
  try {
    await sendPasswordResetEmail(user);
  } catch (error) {
    logger.error({ err: error, userId: user.id, email: user.email }, "Failed to send password reset email");
  }
};

const sendVerificationEmail = async (user: User) => {
  const token = randomToken();
  const tokenHash = sha256(token);
  const expiresAt = addSeconds(new Date(), RedisTTL.emailVerification);

  await db.insert(emailVerifications).values({ userId: user.id, tokenHash, expiresAt });
  await cache.set(RedisKeys.emailVerification(tokenHash), { userId: user.id }, RedisTTL.emailVerification);

  const link = `${appConfig.appUrl}/api/v1/auth/verify-email?token=${encodeURIComponent(token)}`;
  await sendEmail({
    to: user.email,
    subject: "Verify your email",
    text: `Verify your email by opening this link: ${link}`,
  });
};

const appendToken = (baseUrl: string, token: string) => {
  const separator = baseUrl.includes("?") ? "&" : "?";
  return `${baseUrl}${separator}token=${encodeURIComponent(token)}`;
};

const sendPasswordResetEmail = async (user: User) => {
  const token = randomToken();
  const tokenHash = sha256(token);
  const expiresAt = addSeconds(new Date(), RedisTTL.passwordReset);

  await db.insert(passwordResetTokens).values({ userId: user.id, tokenHash, expiresAt });
  await cache.set(RedisKeys.passwordReset(tokenHash), { userId: user.id }, RedisTTL.passwordReset);

  const link = appConfig.passwordResetUrl
    ? appendToken(appConfig.passwordResetUrl, token)
    : `${appConfig.appUrl}/password/reset?token=${encodeURIComponent(token)}`;
  await sendEmail({
    to: user.email,
    subject: "Reset your password",
    text: `Reset your password by opening this link: ${link}`,
  });
};

const createSessionAndTokens = async (userId: string, input: RegisterInput | LoginInput | GoogleInput) => {
  const payload = await createSessionPayload({
    userId,
    device: {
      device_type: input.device_type,
      device_name: input.device_name,
      device_fingerprint: input.device_fingerprint,
    },
  });

  await db.insert(sessions).values(payload.session);

  return issueTokenPair({
    userId,
    sessionId: payload.session.id,
    deviceType: payload.session.deviceType,
    refreshToken: payload.refreshToken,
  });
};

const revokeSessionIds = async (sessionIds: string[]) => {
  await Promise.all(sessionIds.map((sessionId) => redis.del(RedisKeys.refreshToken(sessionId))));
};

const revokeAllUserSessions = async (userId: string) => {
  const activeSessions = await db
    .select({ id: sessions.id })
    .from(sessions)
    .where(and(eq(sessions.userId, userId), eq(sessions.isActive, true)));

  await db
    .update(sessions)
    .set({ isActive: false, revokedAt: new Date(), updatedAt: new Date() })
    .where(eq(sessions.userId, userId));

  await revokeSessionIds(activeSessions.map((session) => session.id));
  await cache.invalidate(RedisKeys.userSessions(userId));
};

const blockCurrentAccessToken = async (token: AccessTokenPayload) => {
  if (!token.exp) {
    return;
  }
  const ttl = Math.max(token.exp - Math.floor(Date.now() / 1000), 1);
  await redis.set(RedisKeys.tokenBlocklist(token.jti), "1", "EX", ttl);
};

export const authService = {
  async register(input: RegisterInput) {
    if (!mailchecker.isValid(input.email)) {
      throw new AppError(422, "DISPOSABLE_EMAIL", "Temporary or disposable emails are not allowed");
    }

    const [existingUser] = await db.select().from(users).where(eq(users.email, input.email)).limit(1);
    if (existingUser) {
      throw new AppError(409, "EMAIL_EXISTS", "Email is already registered");
    }

    const passwordHash = await hashPassword(input.password);
    const [user] = await db.transaction(async (tx) => {
      const [createdUser] = await tx
        .insert(users)
        .values({ email: input.email, name: input.name, isVerified: false })
        .returning();

      if (!createdUser) {
        throw new AppError(500, "USER_CREATE_FAILED", "Unable to create user");
      }

      await tx.insert(userIdentities).values({
        userId: createdUser.id,
        provider: "email",
        providerAccountId: input.email,
        passwordHash,
      });

      await tx.insert(userSettings).values({ userId: createdUser.id });

      return [createdUser];
    });

    const tokens = await createSessionAndTokens(user.id, input);
    const verificationSent = await trySendVerificationEmail(user);
    await cache.invalidate(RedisKeys.userProfile(user.id));

    return {
      user: publicUser(user),
      tokens,
      verification_sent: verificationSent,
      ...(verificationSent ? {} : { message: "Account created, but verification email could not be sent" }),
    };
  },

  async login(input: LoginInput) {
    const [user] = await db.select().from(users).where(and(eq(users.email, input.email), isNull(users.deletedAt))).limit(1);
    if (!user) {
      throw new AuthError("Invalid email or password");
    }

    const [identity] = await db
      .select()
      .from(userIdentities)
      .where(and(eq(userIdentities.userId, user.id), eq(userIdentities.provider, "email")))
      .limit(1);

    if (!identity?.passwordHash || !(await compareHash(input.password, identity.passwordHash))) {
      throw new AuthError("Invalid email or password");
    }

    if (!user.isVerified) {
      const verificationSent = await trySendVerificationEmail(user);
      throw new AppError(403, "EMAIL_NOT_VERIFIED", "Please verify your email before signing in", {
        verification_sent: verificationSent,
      });
    }

    const tokens = await createSessionAndTokens(user.id, input);
    await cache.invalidate(RedisKeys.userSessions(user.id));
    return { user: publicUser(user), tokens };
  },

  async google(input: GoogleInput) {
    let ticket: LoginTicket;

    try {
      ticket = await googleClient.verifyIdToken({
        idToken: input.id_token,
        audience: googleAudiences,
      });
    } catch (error) {
      logger.warn({ err: error, audiences: googleAudiences }, "Google token verification failed");
      throw new AppError(401, "INVALID_GOOGLE_TOKEN", "Google sign-in failed. The Google token is invalid or issued for a different client app.");
    }

    const payload = ticket.getPayload();

    if (!payload?.sub || !payload.email || !payload.email_verified) {
      throw new AuthError("Google account email is not verified");
    }

    const email = payload.email.toLowerCase();
    const [existingIdentity] = await db
      .select()
      .from(userIdentities)
      .where(and(eq(userIdentities.provider, "google"), eq(userIdentities.providerAccountId, payload.sub)))
      .limit(1);

    let user: User | undefined;

    if (existingIdentity) {
      [user] = await db
        .select()
        .from(users)
        .where(and(eq(users.id, existingIdentity.userId), isNull(users.deletedAt)))
        .limit(1);
    } else {
      [user] = await db.select().from(users).where(and(eq(users.email, email), isNull(users.deletedAt))).limit(1);

      if (user) {
        await db.insert(userIdentities).values({
          userId: user.id,
          provider: "google",
          providerAccountId: payload.sub,
        });
        const [updated] = await db
          .update(users)
          .set({
            isVerified: true,
            name: user.name ?? payload.name,
            avatarUrl: user.avatarUrl ?? payload.picture,
            updatedAt: new Date(),
          })
          .where(eq(users.id, user.id))
          .returning();
        user = updated;
      } else {
        const [created] = await db.transaction(async (tx) => {
          const [createdUser] = await tx
            .insert(users)
            .values({
              email,
              name: payload.name,
              avatarUrl: payload.picture,
              isVerified: true,
            })
            .returning();

          if (!createdUser) {
            throw new AppError(500, "USER_CREATE_FAILED", "Unable to create user");
          }

          await tx.insert(userIdentities).values({
            userId: createdUser.id,
            provider: "google",
            providerAccountId: payload.sub,
          });

          await tx.insert(userSettings).values({ userId: createdUser.id });

          return [createdUser];
        });
        user = created;
      }
    }

    if (!user) {
      throw new AuthError("Unable to authenticate Google account");
    }

    const tokens = await createSessionAndTokens(user.id, input);
    await cache.invalidate(RedisKeys.userProfile(user.id), RedisKeys.userSessions(user.id));
    return { user: publicUser(user), tokens };
  },

  async verifyEmail(token: string) {
    const tokenHash = sha256(token);
    const [verification] = await db
      .select()
      .from(emailVerifications)
      .where(
        and(
          eq(emailVerifications.tokenHash, tokenHash),
          isNull(emailVerifications.usedAt),
          gt(emailVerifications.expiresAt, new Date()),
        ),
      )
      .limit(1);

    if (!verification) {
      throw new AuthError("Invalid or expired verification token");
    }

    const [user] = await db
      .update(users)
      .set({ isVerified: true, updatedAt: new Date() })
      .where(eq(users.id, verification.userId))
      .returning();

    await db
      .update(emailVerifications)
      .set({ usedAt: new Date() })
      .where(eq(emailVerifications.id, verification.id));

    await cache.invalidate(RedisKeys.emailVerification(tokenHash), RedisKeys.userProfile(verification.userId));

    return { user: user ? publicUser(user) : null };
  },

  async resendVerification(user: User) {
    if (user.isVerified) {
      return { verification_sent: false, message: "Email is already verified" };
    }

    const verificationSent = await trySendVerificationEmail(user);
    return verificationSent
      ? { verification_sent: true }
      : { verification_sent: false, message: "Verification email could not be sent" };
  },

  async resendVerificationByEmail(input: ResendVerificationInput) {
    const [user] = await db
      .select()
      .from(users)
      .where(and(eq(users.email, input.email), isNull(users.deletedAt)))
      .limit(1);

    if (!user) {
      return { verification_sent: false, message: "If the account exists, a verification email will be sent" };
    }

    if (user.isVerified) {
      return { verification_sent: false, message: "Email is already verified" };
    }

    const verificationSent = await trySendVerificationEmail(user);
    return verificationSent
      ? { verification_sent: true, message: "Verification email sent" }
      : { verification_sent: false, message: "Verification email could not be sent" };
  },

  async refresh(input: RefreshInput) {
    const parsed = parseRefreshToken(input.refresh_token);
    if (!parsed) {
      throw new AuthError("Invalid refresh token");
    }

    const [session] = await db.select().from(sessions).where(eq(sessions.id, parsed.sessionId)).limit(1);
    if (!session) {
      throw new AuthError("Invalid refresh token");
    }

    if (!session.isActive || session.revokedAt || session.expiresAt <= new Date()) {
      await revokeAllUserSessions(session.userId);
      throw new AuthError("Refresh token has been revoked");
    }

    const isValid = await compareHash(input.refresh_token, session.refreshTokenHash);
    if (!isValid) {
      logger.warn({ sessionId: session.id, userId: session.userId }, "Refresh token reuse detected");
      await revokeAllUserSessions(session.userId);
      throw new AuthError("Refresh token reuse detected");
    }

    const nextRefreshToken = createRefreshToken(session.id);
    const refreshTokenHash = await hashPassword(nextRefreshToken);

    await db
      .update(sessions)
      .set({ refreshTokenHash, lastSeenAt: new Date(), updatedAt: new Date() })
      .where(eq(sessions.id, session.id));

    const tokens = await issueTokenPair({
      userId: session.userId,
      sessionId: session.id,
      deviceType: session.deviceType as never,
      refreshToken: nextRefreshToken,
    });

    await cache.invalidate(RedisKeys.userSessions(session.userId));
    return { tokens };
  },

  async logout(userId: string, sessionId: string, token: AccessTokenPayload) {
    await db
      .update(sessions)
      .set({ isActive: false, revokedAt: new Date(), updatedAt: new Date() })
      .where(and(eq(sessions.id, sessionId), eq(sessions.userId, userId)));

    await Promise.all([
      redis.del(RedisKeys.refreshToken(sessionId)),
      blockCurrentAccessToken(token),
      cache.invalidate(RedisKeys.userSessions(userId)),
    ]);

    return { success: true };
  },

  async logoutAll(userId: string, token: AccessTokenPayload) {
    await revokeAllUserSessions(userId);
    await blockCurrentAccessToken(token);
    return { success: true };
  },

  async forgotPassword(input: ForgotPasswordInput) {
    const [user] = await db.select().from(users).where(and(eq(users.email, input.email), isNull(users.deletedAt))).limit(1);
    if (user) {
      await trySendPasswordResetEmail(user);
    }

    return { success: true };
  },

  async resetPassword(input: ResetPasswordInput) {
    const tokenHash = sha256(input.token);
    const [resetToken] = await db
      .select()
      .from(passwordResetTokens)
      .where(
        and(
          eq(passwordResetTokens.tokenHash, tokenHash),
          isNull(passwordResetTokens.usedAt),
          gt(passwordResetTokens.expiresAt, new Date()),
        ),
      )
      .limit(1);

    if (!resetToken) {
      throw new AuthError("Invalid or expired password reset token");
    }

    const [identity] = await db
      .select()
      .from(userIdentities)
      .where(and(eq(userIdentities.userId, resetToken.userId), eq(userIdentities.provider, "email")))
      .limit(1);

    if (!identity) {
      throw new NotFoundError("Email identity");
    }

    await db
      .update(userIdentities)
      .set({ passwordHash: await hashPassword(input.new_password), updatedAt: new Date() })
      .where(eq(userIdentities.id, identity.id));

    await db.update(passwordResetTokens).set({ usedAt: new Date() }).where(eq(passwordResetTokens.id, resetToken.id));
    await revokeAllUserSessions(resetToken.userId);
    await cache.invalidate(RedisKeys.passwordReset(tokenHash), RedisKeys.userProfile(resetToken.userId));

    return { success: true };
  },

  async changePassword(user: User, input: ChangePasswordInput) {
    const [identity] = await db
      .select()
      .from(userIdentities)
      .where(and(eq(userIdentities.userId, user.id), eq(userIdentities.provider, "email")))
      .limit(1);

    if (!identity?.passwordHash || !(await compareHash(input.current_password, identity.passwordHash))) {
      throw new AuthError("Current password is incorrect");
    }

    await db
      .update(userIdentities)
      .set({ passwordHash: await hashPassword(input.new_password), updatedAt: new Date() })
      .where(eq(userIdentities.id, identity.id));

    await revokeAllUserSessions(user.id);
    await cache.invalidate(RedisKeys.userProfile(user.id));

    return { success: true };
  },

  async me(user: User) {
    const identities = await db
      .select({ provider: userIdentities.provider })
      .from(userIdentities)
      .where(eq(userIdentities.userId, user.id));

    return {
      user: publicUser(user),
      providers: identities.map((identity) => identity.provider),
    };
  },
};
