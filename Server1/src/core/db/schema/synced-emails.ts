import {
  boolean,
  index,
  integer,
  jsonb,
  pgTable,
  text,
  timestamp,
  uniqueIndex,
  uuid,
  varchar,
} from "drizzle-orm/pg-core";
import { users } from "./users.js";

export type SyncedEmailParty = { email: string; name?: string };
export type SyncedEmailAttachmentMeta = { filename: string; size: number; mimeType: string };

export const syncedEmails = pgTable(
  "synced_emails",
  {
    id: uuid("id").primaryKey().defaultRandom(),
    userId: uuid("user_id")
      .notNull()
      .references(() => users.id, { onDelete: "cascade" }),
    provider: varchar("provider", { length: 20 }).notNull(),
    providerMessageId: text("provider_message_id").notNull(),
    threadId: text("thread_id"),
    fromEmail: varchar("from_email", { length: 255 }),
    fromName: varchar("from_name", { length: 255 }),
    to: jsonb("to").$type<SyncedEmailParty[]>().default([]).notNull(),
    cc: jsonb("cc").$type<SyncedEmailParty[]>().default([]).notNull(),
    subject: text("subject"),
    snippet: text("snippet"),
    summary: text("summary"),
    keywords: jsonb("keywords").$type<string[]>().default([]).notNull(),
    category: varchar("category", { length: 30 }),
    priorityScore: integer("priority_score"),
    isRead: boolean("is_read").default(false).notNull(),
    isStarred: boolean("is_starred").default(false).notNull(),
    hasAttachments: boolean("has_attachments").default(false).notNull(),
    attachmentMeta: jsonb("attachment_meta").$type<SyncedEmailAttachmentMeta[]>().default([]).notNull(),
    labels: jsonb("labels").$type<string[]>().default([]).notNull(),
    aiProcessed: boolean("ai_processed").default(false).notNull(),
    aiRetryCount: integer("ai_retry_count").default(0).notNull(),
    agentDelivered: boolean("agent_delivered").default(false).notNull(),
    notificationFallback: boolean("notification_fallback").default(false).notNull(),
    receivedAt: timestamp("received_at").notNull(),
    syncedAt: timestamp("synced_at").defaultNow().notNull(),
    updatedAt: timestamp("updated_at").defaultNow().notNull(),
    createdAt: timestamp("created_at").defaultNow().notNull(),
  },
  (t) => ({
    userIdIdx: index("se_user_id_idx").on(t.userId),
    providerMsgUniq: uniqueIndex("se_provider_msg_uniq").on(t.userId, t.provider, t.providerMessageId),
    fromEmailIdx: index("se_from_email_idx").on(t.fromEmail),
    fromNameIdx: index("se_from_name_idx").on(t.fromName),
    subjectIdx: index("se_subject_idx").on(t.subject),
    receivedAtIdx: index("se_received_at_idx").on(t.receivedAt),
    isReadIdx: index("se_is_read_idx").on(t.isRead),
    isStarredIdx: index("se_is_starred_idx").on(t.isStarred),
    categoryIdx: index("se_category_idx").on(t.category),
    aiProcessedIdx: index("se_ai_processed_idx").on(t.aiProcessed),
    threadIdIdx: index("se_thread_id_idx").on(t.threadId),
  }),
);

export type SyncedEmail = typeof syncedEmails.$inferSelect;
export type NewSyncedEmail = typeof syncedEmails.$inferInsert;
