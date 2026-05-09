import type { DeviceType } from "../../core/types/index.js";

export type DeviceInput = {
  device_type: DeviceType;
  device_name?: string | undefined;
  device_fingerprint?: string | undefined;
};

export type AuthTokens = {
  access_token: string;
  refresh_token: string;
  token_type: "Bearer";
  expires_in: number;
};
