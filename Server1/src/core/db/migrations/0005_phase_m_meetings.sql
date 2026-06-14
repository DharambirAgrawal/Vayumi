CREATE TABLE IF NOT EXISTS "meetings" (
  "id" uuid PRIMARY KEY DEFAULT gen_random_uuid() NOT NULL,
  "user_id" uuid NOT NULL REFERENCES "users"("id") ON DELETE cascade,
  "client_meeting_id" text NOT NULL,
  "title" varchar(255) NOT NULL,
  "status" varchar(20) DEFAULT 'ready' NOT NULL,
  "started_at" timestamptz NOT NULL,
  "ended_at" timestamptz,
  "duration_ms" integer DEFAULT 0 NOT NULL,
  "summary" text,
  "key_points" jsonb DEFAULT '[]'::jsonb NOT NULL,
  "action_items" jsonb DEFAULT '[]'::jsonb NOT NULL,
  "transcript" jsonb DEFAULT '[]'::jsonb NOT NULL,
  "suggested_reminders" jsonb DEFAULT '[]'::jsonb NOT NULL,
  "analysis_error" text,
  "recorded_on_device" varchar(120),
  "recorded_session_id" uuid,
  "created_at" timestamp DEFAULT now() NOT NULL,
  "updated_at" timestamp DEFAULT now() NOT NULL,
  "deleted_at" timestamp,
  -- Full-text search over title + summary + transcript (transcript cast to text covers line content).
  "search_vector" tsvector GENERATED ALWAYS AS (
    to_tsvector(
      'english',
      coalesce("title", '') || ' ' || coalesce("summary", '') || ' ' || coalesce("transcript"::text, '')
    )
  ) STORED
);

CREATE UNIQUE INDEX IF NOT EXISTS "meet_user_client_idx" ON "meetings" ("user_id", "client_meeting_id");
CREATE INDEX IF NOT EXISTS "meet_user_id_idx" ON "meetings" ("user_id");
CREATE INDEX IF NOT EXISTS "meet_started_at_idx" ON "meetings" ("started_at");
CREATE INDEX IF NOT EXISTS "meet_status_idx" ON "meetings" ("status");
CREATE INDEX IF NOT EXISTS "meet_search_idx" ON "meetings" USING GIN ("search_vector");

-- Link reminders created from a meeting suggestion (FK kept loose: meeting delete just nulls it).
ALTER TABLE "reminders" ADD COLUMN IF NOT EXISTS "source_meeting_id" uuid REFERENCES "meetings"("id") ON DELETE SET NULL;
CREATE INDEX IF NOT EXISTS "rem_source_meeting_idx" ON "reminders" ("source_meeting_id");
