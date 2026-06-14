import "dotenv/config";
import { z } from "zod";

const envSchema = z
  .object({
    NODE_ENV: z.enum(["development", "test", "production"]).default("development"),
    PORT: z.coerce.number().int().positive().default(3001),
    APP_URL: z.string().url(),
    DATABASE_URL: z.string().min(1),
    DATABASE_SSL_ENABLED: z.enum(["true", "false"]).optional(),
    DATABASE_AUTO_MIGRATE: z.enum(["true", "false"]).optional(),
    REDIS_URL: z.string().min(1).optional(),
    REDIS_HOST: z.string().min(1).optional(),
    REDIS_PORT: z.coerce.number().int().positive().optional(),
    REDIS_USERNAME: z.string().min(1).optional(),
    REDIS_PASSWORD: z.string().min(1).optional(),
    REDIS_TLS_ENABLED: z.enum(["true", "false"]).optional(),
    JWT_PRIVATE_KEY: z.string().min(1),
    JWT_PUBLIC_KEY: z.string().min(1),
    JWT_ACCESS_EXPIRY: z.string().default("15m"),
    JWT_REFRESH_EXPIRY: z.string().default("90d"),
    PASSWORD_RESET_URL: z.string().min(1).optional(),
    FROM_EMAIL: z.string().email(),
    // OCI Email Delivery (HTTPS data-plane API, not SMTP)
    OCI_TENANCY_ID: z.string().min(1),
    OCI_USER_ID: z.string().min(1),
    OCI_FINGERPRINT: z.string().min(1),
    OCI_PRIVATE_KEY: z.string().min(1),
    OCI_PRIVATE_KEY_PASSPHRASE: z.string().min(1).optional(),
    OCI_REGION: z.string().min(1),
    OCI_EMAIL_COMPARTMENT_ID: z.string().min(1),
    ALLOWED_ORIGINS: z.string().min(1),
    GOOGLE_CLIENT_ID: z.string().min(1),
    SUPABASE_URL: z.string().url(),
    SUPABASE_SERVICE_ROLE_KEY: z.string().min(1),
    SUPABASE_STORAGE_BUCKET: z.string().min(1),
    SUPABASE_STORAGE_PUBLIC_URL: z.string().url().optional(),
    ENCRYPTION_KEY: z.string().min(1),
    APNS_KEY_ID: z.string().min(1),
    APNS_TEAM_ID: z.string().min(1),
    APNS_KEY_PATH: z.string().min(1),
    APNS_BUNDLE_ID: z.string().min(1),
    FCM_SERVICE_ACCOUNT_PATH: z.string().min(1),
    GOOGLE_CLIENT_SECRET: z.string().min(1),
    GOOGLE_REDIRECT_URI: z.string().min(1),
    MICROSOFT_CLIENT_ID: z.string().min(1),
    MICROSOFT_CLIENT_SECRET: z.string().min(1),
    MICROSOFT_REDIRECT_URI: z.string().min(1),
    MICROSOFT_TENANT_ID: z.string().min(1),
    SERVER2_INTERNAL_URL: z.string().optional().default(""),
    EMAIL_SYNC_WINDOW_DAYS: z.coerce.number().int().positive().default(90),
    EMAIL_AI_CLASSIFY_TIMEOUT_MS: z.coerce.number().int().positive().default(3000),
    EMAIL_NOTIFY_TIMEOUT_MS: z.coerce.number().int().positive().default(2000),
    EMAIL_POLL_INTERVAL_MINUTES: z.coerce.number().int().positive().default(3),
    EMAIL_CLASSIFY_MAX_BODY_CHARS: z.coerce.number().int().positive().default(2000),
    INTERNAL_REMINDER_SECRET: z.string().min(1),
    REMINDER_FIRE_BATCH_SIZE: z.coerce.number().int().positive().default(100),
    REMINDER_AGENT_EVENT_TIMEOUT_MS: z.coerce.number().int().positive().default(2000),
  })
  .superRefine((env, ctx) => {
    if (env.SERVER2_INTERNAL_URL && env.SERVER2_INTERNAL_URL.trim() !== "") {
      const parsed = z.string().url().safeParse(env.SERVER2_INTERNAL_URL.trim());
      if (!parsed.success) {
        ctx.addIssue({
          code: z.ZodIssueCode.custom,
          path: ["SERVER2_INTERNAL_URL"],
          message: "Must be a valid URL when set",
        });
      }
    }

    const hasRedisUrl = Boolean(env.REDIS_URL);
    const hasRedisObjectConfig = Boolean(env.REDIS_HOST && env.REDIS_PORT && env.REDIS_PASSWORD);

    if (!hasRedisUrl && !hasRedisObjectConfig) {
      ctx.addIssue({
        code: z.ZodIssueCode.custom,
        path: ["REDIS_URL"],
        message: "Provide REDIS_URL or REDIS_HOST/REDIS_PORT/REDIS_PASSWORD",
      });
    }
  });

const parsed = envSchema.safeParse(process.env);

if (!parsed.success) {
  const details = parsed.error.issues.map((issue) => `${issue.path.join(".")}: ${issue.message}`).join("; ");
  throw new Error(`Invalid environment configuration: ${details}`);
}

export const env = parsed.data;
export type Env = typeof env;
