CREATE TABLE IF NOT EXISTS "reminders" (
  "id" uuid PRIMARY KEY DEFAULT gen_random_uuid() NOT NULL,
  "user_id" uuid NOT NULL REFERENCES "users"("id") ON DELETE cascade,
  "title" varchar(255) NOT NULL,
  "body" text,
  "remind_at" timestamptz NOT NULL,
  "timezone" varchar(60) NOT NULL,
  "recurrence" varchar(20),
  "rrule" text,
  "next_fire_at" timestamptz NOT NULL,
  "status" varchar(20) DEFAULT 'pending' NOT NULL,
  "source" varchar(20) DEFAULT 'user' NOT NULL,
  "snooze_until" timestamptz,
  "fired_at" timestamptz,
  "fire_count" integer DEFAULT 0 NOT NULL,
  "max_fire_count" integer,
  "agent_delivered" boolean DEFAULT false NOT NULL,
  "push_delivered" boolean DEFAULT false NOT NULL,
  "created_at" timestamp DEFAULT now() NOT NULL,
  "updated_at" timestamp DEFAULT now() NOT NULL
);

CREATE INDEX IF NOT EXISTS "rem_user_id_idx" ON "reminders" ("user_id");
CREATE INDEX IF NOT EXISTS "rem_next_fire_at_idx" ON "reminders" ("next_fire_at");
CREATE INDEX IF NOT EXISTS "rem_status_idx" ON "reminders" ("status");
CREATE INDEX IF NOT EXISTS "rem_user_status_idx" ON "reminders" ("user_id", "status");
