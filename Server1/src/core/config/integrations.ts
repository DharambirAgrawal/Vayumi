import { env } from "./index.js";

const trimTrailingSlash = (value: string) => value.replace(/\/$/, "");

export const integrationsConfig = {
  server2InternalBaseUrl: env.SERVER2_INTERNAL_URL.trim()
    ? trimTrailingSlash(env.SERVER2_INTERNAL_URL.trim())
    : "",
};
