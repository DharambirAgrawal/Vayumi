import { env } from "./index.js";

export const appConfig = {
  nodeEnv: env.NODE_ENV,
  port: env.PORT,
  appUrl: env.APP_URL.replace(/\/$/, ""),
  passwordResetUrl: env.PASSWORD_RESET_URL?.replace(/\/$/, ""),
  cors: {
    origins: env.ALLOWED_ORIGINS.split(",").map((origin) => origin.trim()).filter(Boolean),
  },
  rateLimit: {
    global: { windowSeconds: 60, max: 300 },
    auth: { windowSeconds: 60, max: 10 },
  },
};
