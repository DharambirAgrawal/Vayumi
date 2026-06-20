ALTER TABLE "password_reset_tokens" ADD COLUMN IF NOT EXISTS "attempts" integer DEFAULT 0 NOT NULL;
