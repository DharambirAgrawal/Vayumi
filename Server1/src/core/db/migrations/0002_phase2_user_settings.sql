CREATE TABLE IF NOT EXISTS "user_settings" (
  "user_id" uuid PRIMARY KEY REFERENCES "users"("id") ON DELETE cascade,
  "notifications" jsonb DEFAULT '{}'::jsonb NOT NULL,
  "privacy" jsonb DEFAULT '{}'::jsonb NOT NULL,
  "appearance" jsonb DEFAULT '{}'::jsonb NOT NULL,
  "updated_at" timestamp DEFAULT now() NOT NULL
);

INSERT INTO "user_settings" ("user_id")
SELECT "id" FROM "users"
WHERE NOT EXISTS (
  SELECT 1 FROM "user_settings" WHERE "user_settings"."user_id" = "users"."id"
);
