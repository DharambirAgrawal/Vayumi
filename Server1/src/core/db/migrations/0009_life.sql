-- Life: the user's structured personal memory (trackers + entries). Offline-first,
-- synced idempotently on (user_id, client_id). Media stays on the device.

CREATE TABLE IF NOT EXISTS "life_tabs" (
  "id" uuid PRIMARY KEY DEFAULT gen_random_uuid() NOT NULL,
  "user_id" uuid NOT NULL REFERENCES "users"("id") ON DELETE cascade,
  "client_tab_id" text NOT NULL,
  "display_name" varchar(120) NOT NULL,
  "tab_type" varchar(60) NOT NULL,
  "layout" varchar(20) DEFAULT 'timeline' NOT NULL,
  "secondary_layout" varchar(20),
  "icon" varchar(60) DEFAULT 'sparkles-outline' NOT NULL,
  "color" varchar(20) DEFAULT '#EE6A5E' NOT NULL,
  "purpose" text,
  "schema" jsonb NOT NULL,
  "settings" jsonb DEFAULT '{}'::jsonb NOT NULL,
  "position" integer DEFAULT 0 NOT NULL,
  "status" varchar(20) DEFAULT 'active' NOT NULL,
  "source" varchar(20) DEFAULT 'user' NOT NULL,
  "client_created_at" timestamptz,
  "client_updated_at" timestamptz,
  "created_at" timestamp DEFAULT now() NOT NULL,
  "updated_at" timestamp DEFAULT now() NOT NULL,
  "deleted_at" timestamp
);

CREATE UNIQUE INDEX IF NOT EXISTS "life_tab_user_client_idx" ON "life_tabs" ("user_id", "client_tab_id");
CREATE INDEX IF NOT EXISTS "life_tab_user_id_idx" ON "life_tabs" ("user_id");
CREATE INDEX IF NOT EXISTS "life_tab_updated_at_idx" ON "life_tabs" ("updated_at");

CREATE TABLE IF NOT EXISTS "life_entries" (
  "id" uuid PRIMARY KEY DEFAULT gen_random_uuid() NOT NULL,
  "user_id" uuid NOT NULL REFERENCES "users"("id") ON DELETE cascade,
  "client_entry_id" text NOT NULL,
  "client_tab_id" text NOT NULL,
  "data" jsonb NOT NULL,
  "occurred_at" timestamptz NOT NULL,
  "source" varchar(20) DEFAULT 'user' NOT NULL,
  "raw_input" text,
  "reminder_id" text,
  "client_created_at" timestamptz,
  "client_updated_at" timestamptz,
  "created_at" timestamp DEFAULT now() NOT NULL,
  "updated_at" timestamp DEFAULT now() NOT NULL,
  "deleted_at" timestamp
);

CREATE UNIQUE INDEX IF NOT EXISTS "life_entry_user_client_idx" ON "life_entries" ("user_id", "client_entry_id");
CREATE INDEX IF NOT EXISTS "life_entry_user_tab_idx" ON "life_entries" ("user_id", "client_tab_id");
CREATE INDEX IF NOT EXISTS "life_entry_occurred_at_idx" ON "life_entries" ("occurred_at");
CREATE INDEX IF NOT EXISTS "life_entry_updated_at_idx" ON "life_entries" ("updated_at");
