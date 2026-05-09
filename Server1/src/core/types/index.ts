import type { JwtPayload } from "jsonwebtoken";
import type { Session } from "../db/schema/sessions.js";
import type { User } from "../db/schema/users.js";

export type { User } from "../db/schema/users.js";
export type { Session } from "../db/schema/sessions.js";

export const deviceTypes = ["mobile_ios", "mobile_android", "web", "hardware"] as const;
export type DeviceType = (typeof deviceTypes)[number];

export const pushPlatforms = ["ios", "android"] as const;
export type PushPlatform = (typeof pushPlatforms)[number];

export type AuthProvider = "email" | "google";

export interface AccessTokenPayload extends JwtPayload {
  sub: string;
  sid: string;
  jti: string;
  device_type: DeviceType;
  scopes: string[];
}

export interface AuthContext {
  user: User;
  session: Session;
  token: AccessTokenPayload;
}
