CREATE TABLE IF NOT EXISTS "rate_limits" (
  "key" text PRIMARY KEY,
  "count" integer NOT NULL DEFAULT 0,
  "expires_at" timestamp NOT NULL
);

CREATE INDEX IF NOT EXISTS "rate_limits_expires_at_idx" ON "rate_limits" ("expires_at");
