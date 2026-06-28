-- Memory: curated long-term facts the assistant remembers about the user.
-- Synced idempotently on (user_id, key); soft delete propagates a "forget".

CREATE TABLE IF NOT EXISTS "memory_facts" (
  "id" uuid PRIMARY KEY DEFAULT gen_random_uuid() NOT NULL,
  "user_id" uuid NOT NULL REFERENCES "users"("id") ON DELETE cascade,
  "key" varchar(120) NOT NULL,
  "value" text NOT NULL,
  "category" varchar(20) DEFAULT 'misc' NOT NULL,
  "source" varchar(20) DEFAULT 'ai' NOT NULL,
  "pinned" boolean DEFAULT false NOT NULL,
  "client_updated_at" timestamptz,
  "created_at" timestamp DEFAULT now() NOT NULL,
  "updated_at" timestamp DEFAULT now() NOT NULL,
  "deleted_at" timestamp
);

CREATE UNIQUE INDEX IF NOT EXISTS "mem_user_key_idx" ON "memory_facts" ("user_id", "key");
CREATE INDEX IF NOT EXISTS "mem_fact_user_id_idx" ON "memory_facts" ("user_id");
CREATE INDEX IF NOT EXISTS "mem_fact_updated_at_idx" ON "memory_facts" ("updated_at");
