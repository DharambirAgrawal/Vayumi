import { boolean, index, integer, pgTable, text, timestamp, uuid, varchar } from "drizzle-orm/pg-core";
import { users } from "./users.js";

export const reminderStatuses = ["pending", "fired", "snoozed", "cancelled"] as const;
export type ReminderStatus = (typeof reminderStatuses)[number];

export const reminderSources = ["user", "agent"] as const;
export type ReminderSource = (typeof reminderSources)[number];

export const reminderRecurrences = ["daily", "weekly", "monthly", "custom"] as const;
export type ReminderRecurrence = (typeof reminderRecurrences)[number];

export const reminders = pgTable(
  "reminders",
  {
    id: uuid("id").primaryKey().defaultRandom(),
    userId: uuid("user_id")
      .notNull()
      .references(() => users.id, { onDelete: "cascade" }),
    title: varchar("title", { length: 255 }).notNull(),
    body: text("body"),
    remindAt: timestamp("remind_at", { withTimezone: true }).notNull(),
    timezone: varchar("timezone", { length: 60 }).notNull(),
    recurrence: varchar("recurrence", { length: 20 }),
    rrule: text("rrule"),
    nextFireAt: timestamp("next_fire_at", { withTimezone: true }).notNull(),
    status: varchar("status", { length: 20 }).notNull().default("pending"),
    source: varchar("source", { length: 20 }).notNull().default("user"),
    snoozeUntil: timestamp("snooze_until", { withTimezone: true }),
    firedAt: timestamp("fired_at", { withTimezone: true }),
    fireCount: integer("fire_count").default(0).notNull(),
    maxFireCount: integer("max_fire_count"),
    agentDelivered: boolean("agent_delivered").default(false).notNull(),
    pushDelivered: boolean("push_delivered").default(false).notNull(),
    // Optional link to the meeting whose suggestion created this reminder.
    // FK to meetings(id) ON DELETE SET NULL is enforced in migration SQL (avoids a circular import).
    sourceMeetingId: uuid("source_meeting_id"),
    createdAt: timestamp("created_at").defaultNow().notNull(),
    updatedAt: timestamp("updated_at").defaultNow().notNull(),
  },
  (table) => ({
    userIdIdx: index("rem_user_id_idx").on(table.userId),
    nextFireAtIdx: index("rem_next_fire_at_idx").on(table.nextFireAt),
    statusIdx: index("rem_status_idx").on(table.status),
    userStatusIdx: index("rem_user_status_idx").on(table.userId, table.status),
    sourceMeetingIdx: index("rem_source_meeting_idx").on(table.sourceMeetingId),
  }),
);

export type Reminder = typeof reminders.$inferSelect;
export type NewReminder = typeof reminders.$inferInsert;
