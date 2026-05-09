import { randomUUID } from "node:crypto";
import jwt from "jsonwebtoken";
import type { SignOptions } from "jsonwebtoken";
import { jwtConfig } from "../config/jwt.js";
import type { AccessTokenPayload, DeviceType } from "../types/index.js";
import { secondsFromDuration } from "./date.js";

export const signAccessToken = (input: {
  userId: string;
  sessionId: string;
  deviceType: DeviceType;
  scopes: string[];
}) => {
  const jti = randomUUID();
  const options: SignOptions = {
    algorithm: jwtConfig.algorithm,
    subject: input.userId,
    expiresIn: jwtConfig.accessExpiry as NonNullable<SignOptions["expiresIn"]>,
    jwtid: jti,
  };

  const token = jwt.sign(
    {
      sid: input.sessionId,
      device_type: input.deviceType,
      scopes: input.scopes,
    },
    jwtConfig.privateKey,
    options,
  );

  return {
    token,
    jti,
    expiresIn: secondsFromDuration(jwtConfig.accessExpiry),
  };
};

export const verifyAccessToken = (token: string): AccessTokenPayload => {
  return jwt.verify(token, jwtConfig.publicKey, {
    algorithms: [jwtConfig.algorithm],
  }) as AccessTokenPayload;
};

export const decodeAccessToken = (token: string) => jwt.decode(token) as AccessTokenPayload | null;
