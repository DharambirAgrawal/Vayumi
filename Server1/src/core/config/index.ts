import "dotenv/config";
import { z } from "zod";

// Treat a present-but-empty env var (e.g. `FOO=`) the same as unset, so optional
// integrations can be left blank in .env without failing validation.
const optionalString = z.preprocess(
  (value) => (typeof value === "string" && value.trim() === "" ? undefined : value),
  z.string().min(1).optional(),
);

const envSchema = z
  .object({
    NODE_ENV: z.enum(["development", "test", "production"]).default("development"),
    PORT: z.coerce.number().int().positive().default(3001),
    APP_URL: z.string().url(),
    DATABASE_URL: z.string().min(1),
    DATABASE_SSL_ENABLED: z.enum(["true", "false"]).optional(),
    DATABASE_AUTO_MIGRATE: z.enum(["true", "false"]).optional(),
    JWT_PRIVATE_KEY: z.string().min(1),
    JWT_PUBLIC_KEY: z.string().min(1),
    JWT_ACCESS_EXPIRY: z.string().default("15m"),
    JWT_REFRESH_EXPIRY: z.string().default("90d"),
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
    // Audience for Sign in with Apple identity tokens — defaults to APNS_BUNDLE_ID
    // below if unset, since for the native flow they're the same bundle id.
    APPLE_BUNDLE_ID: z.string().min(1).optional(),
    SUPABASE_URL: z.string().url(),
    SUPABASE_SERVICE_ROLE_KEY: z.string().min(1),
    SUPABASE_STORAGE_BUCKET: z.string().min(1),
    SUPABASE_STORAGE_PUBLIC_URL: z.string().url().optional(),
    ENCRYPTION_KEY: z.string().min(1),
    // Push notifications are optional until the Apple/Firebase developer setup
    // is done — the server boots and runs (auth, email, reminders) without them,
    // and push sending no-ops when unset.
    APNS_BUNDLE_ID: optionalString,
    FCM_SERVICE_ACCOUNT_PATH: optionalString,
    SERVER2_INTERNAL_URL: z.string().optional().default(""),
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
  });

const parsed = envSchema.safeParse(process.env);

if (!parsed.success) {
  const details = parsed.error.issues.map((issue) => `${issue.path.join(".")}: ${issue.message}`).join("; ");
  throw new Error(`Invalid environment configuration: ${details}`);
}

export const env = parsed.data;
export type Env = typeof env;
