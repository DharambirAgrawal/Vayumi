import { index, integer, jsonb, pgTable, text, timestamp, uniqueIndex, uuid, varchar } from "drizzle-orm/pg-core";
import { users } from "./users.js";

// Only terminal states are ever uploaded — transient recording/processing stay on-device.
export const meetingStatuses = ["ready", "error", "interrupted"] as const;
export type MeetingStatus = (typeof meetingStatuses)[number];

// Meeting TEXT + metadata only. Audio never leaves the device (encrypted, device-bound key),
// so there is intentionally no audio column and no global "has audio" flag — only
// `recorded_on_device` for display on other devices.
export const meetings = pgTable(
  "meetings",
  {
    id: uuid("id").primaryKey().defaultRandom(),
    userId: uuid("user_id")
      .notNull()
      .references(() => users.id, { onDelete: "cascade" }),
    clientMeetingId: text("client_meeting_id").notNull(),
    title: varchar("title", { length: 255 }).notNull(),
    status: varchar("status", { length: 20 }).notNull().default("ready"),
    startedAt: timestamp("started_at", { withTimezone: true }).notNull(),
    endedAt: timestamp("ended_at", { withTimezone: true }),
    durationMs: integer("duration_ms").notNull().default(0),
    summary: text("summary"),
    keyPoints: jsonb("key_points").default([]).notNull(),
    actionItems: jsonb("action_items").default([]).notNull(),
    transcript: jsonb("transcript").default([]).notNull(),
    suggestedReminders: jsonb("suggested_reminders").default([]).notNull(),
    analysisError: text("analysis_error"),
    recordedOnDevice: varchar("recorded_on_device", { length: 120 }),
    recordedSessionId: uuid("recorded_session_id"),
    createdAt: timestamp("created_at").defaultNow().notNull(),
    updatedAt: timestamp("updated_at").defaultNow().notNull(),
    deletedAt: timestamp("deleted_at"),
  },
  (table) => ({
    userClientUniq: uniqueIndex("meet_user_client_idx").on(table.userId, table.clientMeetingId),
    userIdIdx: index("meet_user_id_idx").on(table.userId),
    startedAtIdx: index("meet_started_at_idx").on(table.startedAt),
    statusIdx: index("meet_status_idx").on(table.status),
    // GIN full-text index on a generated `search_vector` column added in migration SQL.
  }),
);

export type Meeting = typeof meetings.$inferSelect;
export type NewMeeting = typeof meetings.$inferInsert;
