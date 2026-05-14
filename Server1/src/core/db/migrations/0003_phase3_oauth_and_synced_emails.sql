CREATE TABLE IF NOT EXISTS "oauth_integrations" (
  "id" uuid PRIMARY KEY DEFAULT gen_random_uuid() NOT NULL,
  "user_id" uuid NOT NULL REFERENCES "users"("id") ON DELETE cascade,
  "provider" varchar(30) NOT NULL,
  "provider_account_id" text NOT NULL,
  "access_token" text,
  "refresh_token" text,
  "access_token_expires_at" timestamp,
  "scopes" text,
  "sync_state" jsonb DEFAULT '{}'::jsonb NOT NULL,
  "webhook_active" boolean DEFAULT false NOT NULL,
  "webhook_resource_id" text,
  "webhook_expires_at" timestamp,
  "created_at" timestamp DEFAULT now() NOT NULL,
  "updated_at" timestamp DEFAULT now() NOT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS "oi_user_provider_idx" ON "oauth_integrations" ("user_id", "provider");

CREATE TABLE IF NOT EXISTS "synced_emails" (
  "id" uuid PRIMARY KEY DEFAULT gen_random_uuid() NOT NULL,
  "user_id" uuid NOT NULL REFERENCES "users"("id") ON DELETE cascade,
  "provider" varchar(20) NOT NULL,
  "provider_message_id" text NOT NULL,
  "thread_id" text,
  "from_email" varchar(255),
  "from_name" varchar(255),
  "to" jsonb DEFAULT '[]'::jsonb NOT NULL,
  "cc" jsonb DEFAULT '[]'::jsonb NOT NULL,
  "subject" text,
  "snippet" text,
  "summary" text,
  "keywords" jsonb DEFAULT '[]'::jsonb NOT NULL,
  "category" varchar(30),
  "priority_score" integer,
  "is_read" boolean DEFAULT false NOT NULL,
  "is_starred" boolean DEFAULT false NOT NULL,
  "has_attachments" boolean DEFAULT false NOT NULL,
  "attachment_meta" jsonb DEFAULT '[]'::jsonb NOT NULL,
  "labels" jsonb DEFAULT '[]'::jsonb NOT NULL,
  "ai_processed" boolean DEFAULT false NOT NULL,
  "ai_retry_count" integer DEFAULT 0 NOT NULL,
  "agent_delivered" boolean DEFAULT false NOT NULL,
  "notification_fallback" boolean DEFAULT false NOT NULL,
  "received_at" timestamp NOT NULL,
  "synced_at" timestamp DEFAULT now() NOT NULL,
  "updated_at" timestamp DEFAULT now() NOT NULL,
  "created_at" timestamp DEFAULT now() NOT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS "se_provider_msg_uniq" ON "synced_emails" ("user_id", "provider", "provider_message_id");
CREATE INDEX IF NOT EXISTS "se_user_id_idx" ON "synced_emails" ("user_id");
CREATE INDEX IF NOT EXISTS "se_from_email_idx" ON "synced_emails" ("from_email");
CREATE INDEX IF NOT EXISTS "se_from_name_idx" ON "synced_emails" ("from_name");
CREATE INDEX IF NOT EXISTS "se_subject_idx" ON "synced_emails" ("subject");
CREATE INDEX IF NOT EXISTS "se_received_at_idx" ON "synced_emails" ("received_at");
CREATE INDEX IF NOT EXISTS "se_is_read_idx" ON "synced_emails" ("is_read");
CREATE INDEX IF NOT EXISTS "se_is_starred_idx" ON "synced_emails" ("is_starred");
CREATE INDEX IF NOT EXISTS "se_category_idx" ON "synced_emails" ("category");
CREATE INDEX IF NOT EXISTS "se_ai_processed_idx" ON "synced_emails" ("ai_processed");
CREATE INDEX IF NOT EXISTS "se_thread_id_idx" ON "synced_emails" ("thread_id");
CREATE INDEX IF NOT EXISTS "se_keywords_gin_idx" ON "synced_emails" USING GIN ("keywords");
