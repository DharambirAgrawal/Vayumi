ALTER TABLE "email_verifications" ADD COLUMN IF NOT EXISTS "attempts" integer DEFAULT 0 NOT NULL;
