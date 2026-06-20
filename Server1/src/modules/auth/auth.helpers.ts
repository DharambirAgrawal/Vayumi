import { randomUUID } from "node:crypto";
import { sessions } from "../../core/db/schema/index.js";
import { TokenLifetimes } from "../../core/auth/tokenLifetimes.js";
import type { DeviceType } from "../../core/types/index.js";
import { addSeconds } from "../../core/utils/date.js";
import { hashPassword, randomToken } from "../../core/utils/crypto.js";
import { signAccessToken } from "../../core/utils/jwt.js";
import type { AuthTokens, DeviceInput } from "./auth.types.js";

export const createRefreshToken = (sessionId: string) => `${sessionId}.${randomToken(48)}`;

export const parseRefreshToken = (token: string) => {
  const [sessionId, secret] = token.split(".");
  if (!sessionId || !secret) {
    return null;
  }
  return { sessionId, secret };
};

export const createSessionPayload = async (input: {
  userId: string;
  device: DeviceInput;
}) => {
  const sessionId = randomUUID();
  const refreshToken = createRefreshToken(sessionId);
  const refreshTokenHash = await hashPassword(refreshToken);
  const expiresAt = addSeconds(new Date(), TokenLifetimes.refreshTokenSeconds);

  return {
    session: {
      id: sessionId,
      userId: input.userId,
      deviceType: input.device.device_type,
      deviceName: input.device.device_name,
      deviceFingerprint: input.device.device_fingerprint,
      refreshTokenHash,
      expiresAt,
    } satisfies typeof sessions.$inferInsert,
    refreshToken,
  };
};

export const issueTokenPair = async (input: {
  userId: string;
  sessionId: string;
  deviceType: DeviceType;
  refreshToken: string;
  scopes?: string[];
}): Promise<AuthTokens> => {
  const access = signAccessToken({
    userId: input.userId,
    sessionId: input.sessionId,
    deviceType: input.deviceType,
    scopes: input.scopes ?? ["user"],
  });

  return {
    access_token: access.token,
    refresh_token: input.refreshToken,
    token_type: "Bearer",
    expires_in: access.expiresIn,
  };
};
