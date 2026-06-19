import { OAuth2Client, type LoginTicket } from "google-auth-library";
import { createRemoteJWKSet, jwtVerify } from "jose";
import { and, desc, eq, gt, isNull } from "drizzle-orm";
import mailchecker from "mailchecker";
import * as common from "oci-common";
import * as emaildataplane from "oci-emaildataplane";
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
import { compareHash, generateNumericCode, hashPassword, randomToken, sha256 } from "../../core/utils/crypto.js";
import type { AccessTokenPayload, User } from "../../core/types/index.js";
import { logger } from "../../core/utils/logger.js";
import {
  createRefreshToken,
  createSessionPayload,
  issueTokenPair,
  parseRefreshToken,
} from "./auth.helpers.js";
import type {
  AppleInput,
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

const appleJwks = createRemoteJWKSet(new URL("https://appleid.apple.com/auth/keys"));
const appleAudience = env.APPLE_BUNDLE_ID || env.APNS_BUNDLE_ID;

const ociAuthProvider = new common.SimpleAuthenticationDetailsProvider(
  env.OCI_TENANCY_ID,
  env.OCI_USER_ID,
  env.OCI_FINGERPRINT,
  env.OCI_PRIVATE_KEY.replace(/\\n/g, "\n"),
  env.OCI_PRIVATE_KEY_PASSPHRASE ?? null,
  common.Region.fromRegionId(env.OCI_REGION),
);

const emailClient = new emaildataplane.EmailDPClient({ authenticationDetailsProvider: ociAuthProvider });

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
  await emailClient.submitEmail({
    submitEmailDetails: {
      sender: {
        senderAddress: { email: env.FROM_EMAIL },
        compartmentId: env.OCI_EMAIL_COMPARTMENT_ID,
      },
      recipients: { to: [{ email: input.to }] },
      subject: input.subject,
      bodyText: input.text,
    },
  });
};

const MAX_VERIFICATION_ATTEMPTS = 5;

const trySendVerificationEmail = async (user: User) => {
  try {
    await sendVerificationEmail(user);
    return true;
  } catch (error) {
    logger.error({ err: error, userId: user.id, email: user.email }, "Failed to send verification email");
    return false;
  }
};

const isVerificationOnCooldown = (userId: string) =>
  cache.get<string>(RedisKeys.emailVerificationCooldown(userId));

const sendVerificationCodeWithCooldown = async (user: User) => {
  const sent = await trySendVerificationEmail(user);
  if (sent) {
    await cache.set(RedisKeys.emailVerificationCooldown(user.id), "1", RedisTTL.emailVerificationCooldown);
  }
  return sent;
};

const trySendPasswordResetEmail = async (user: User) => {
  try {
    await sendPasswordResetEmail(user);
  } catch (error) {
    logger.error({ err: error, userId: user.id, email: user.email }, "Failed to send password reset email");
  }
};

const sendVerificationEmail = async (user: User) => {
  const code = generateNumericCode();
  const tokenHash = sha256(code);
  const expiresAt = addSeconds(new Date(), RedisTTL.emailVerificationCode);

  await db.insert(emailVerifications).values({ userId: user.id, tokenHash, expiresAt });

  await sendEmail({
    to: user.email,
    subject: "Your Vayumi verification code",
    text: `Your Vayumi verification code is ${code}. It expires in 10 minutes. If you didn't request this, you can safely ignore this email.`,
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

const createSessionAndTokens = async (
  userId: string,
  input: RegisterInput | LoginInput | GoogleInput | AppleInput,
) => {
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
    const verificationSent = await sendVerificationCodeWithCooldown(user);
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
      const onCooldown = await isVerificationOnCooldown(user.id);
      const verificationSent = onCooldown ? true : await sendVerificationCodeWithCooldown(user);
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

  async apple(input: AppleInput) {
    let payload: Record<string, unknown>;

    try {
      const { payload: verified } = await jwtVerify(input.id_token, appleJwks, {
        issuer: "https://appleid.apple.com",
        audience: appleAudience,
      });
      payload = verified;
    } catch (error) {
      logger.warn({ err: error, audience: appleAudience }, "Apple token verification failed");
      throw new AppError(401, "INVALID_APPLE_TOKEN", "Apple sign-in failed. The Apple token is invalid or issued for a different client app.");
    }

    const sub = typeof payload.sub === "string" ? payload.sub : undefined;
    const emailClaim = typeof payload.email === "string" ? payload.email : undefined;
    const emailVerified = payload.email_verified === true || payload.email_verified === "true";

    if (!sub || !emailClaim || !emailVerified) {
      throw new AuthError("Apple account email is not verified");
    }

    const email = emailClaim.toLowerCase();
    const [existingIdentity] = await db
      .select()
      .from(userIdentities)
      .where(and(eq(userIdentities.provider, "apple"), eq(userIdentities.providerAccountId, sub)))
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
          provider: "apple",
          providerAccountId: sub,
        });
        const [updated] = await db
          .update(users)
          .set({
            isVerified: true,
            name: user.name ?? input.full_name,
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
              name: input.full_name,
              isVerified: true,
            })
            .returning();

          if (!createdUser) {
            throw new AppError(500, "USER_CREATE_FAILED", "Unable to create user");
          }

          await tx.insert(userIdentities).values({
            userId: createdUser.id,
            provider: "apple",
            providerAccountId: sub,
          });

          await tx.insert(userSettings).values({ userId: createdUser.id });

          return [createdUser];
        });
        user = created;
      }
    }

    if (!user) {
      throw new AuthError("Unable to authenticate Apple account");
    }

    const tokens = await createSessionAndTokens(user.id, input);
    await cache.invalidate(RedisKeys.userProfile(user.id), RedisKeys.userSessions(user.id));
    return { user: publicUser(user), tokens };
  },

  async verifyEmailCode(input: { code: string; userId?: string; email?: string }) {
    let user: User | undefined;

    if (input.userId) {
      [user] = await db.select().from(users).where(eq(users.id, input.userId)).limit(1);
    } else if (input.email) {
      [user] = await db
        .select()
        .from(users)
        .where(and(eq(users.email, input.email), isNull(users.deletedAt)))
        .limit(1);
    }

    if (!user) {
      throw new AuthError("Invalid or expired verification code");
    }

    if (user.isVerified) {
      return { user: publicUser(user), already_verified: true };
    }

    const [verification] = await db
      .select()
      .from(emailVerifications)
      .where(
        and(
          eq(emailVerifications.userId, user.id),
          isNull(emailVerifications.usedAt),
          gt(emailVerifications.expiresAt, new Date()),
        ),
      )
      .orderBy(desc(emailVerifications.createdAt))
      .limit(1);

    if (!verification) {
      throw new AuthError("Invalid or expired verification code");
    }

    if (verification.attempts >= MAX_VERIFICATION_ATTEMPTS) {
      throw new AppError(429, "TOO_MANY_ATTEMPTS", "Too many incorrect attempts. Please request a new code");
    }

    if (sha256(input.code) !== verification.tokenHash) {
      await db
        .update(emailVerifications)
        .set({ attempts: verification.attempts + 1 })
        .where(eq(emailVerifications.id, verification.id));
      throw new AuthError("Incorrect verification code");
    }

    const [updatedUser] = await db
      .update(users)
      .set({ isVerified: true, updatedAt: new Date() })
      .where(eq(users.id, user.id))
      .returning();

    await db.update(emailVerifications).set({ usedAt: new Date() }).where(eq(emailVerifications.id, verification.id));
    await cache.invalidate(RedisKeys.userProfile(user.id));

    return { user: updatedUser ? publicUser(updatedUser) : null };
  },

  async resendVerification(user: User) {
    if (user.isVerified) {
      return { verification_sent: false, message: "Email is already verified" };
    }

    if (await isVerificationOnCooldown(user.id)) {
      return { verification_sent: false, message: "Please wait a moment before requesting another code" };
    }

    const verificationSent = await sendVerificationCodeWithCooldown(user);
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
      return { verification_sent: false, message: "If the account exists, a verification code will be sent" };
    }

    if (user.isVerified) {
      return { verification_sent: false, message: "Email is already verified" };
    }

    if (await isVerificationOnCooldown(user.id)) {
      return { verification_sent: false, message: "Please wait a moment before requesting another code" };
    }

    const verificationSent = await sendVerificationCodeWithCooldown(user);
    return verificationSent
      ? { verification_sent: true, message: "Verification code sent" }
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
