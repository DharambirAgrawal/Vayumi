import { index, integer, jsonb, pgTable, text, timestamp, uniqueIndex, uuid, varchar } from "drizzle-orm/pg-core";
import { users } from "./users.js";

// Life is the user's structured personal memory (trackers + their logged entries).
// It is offline-first on the device: every row carries the device-generated client
// id so sync is idempotent on (user_id, client_id), exactly like meetings. Media
// (scanned photos) NEVER leaves the device — there is no media column here, only the
// validated entry `data`. Soft delete (deleted_at) lets other devices reconcile.

export const lifeTabStatuses = ["active", "archived"] as const;
export type LifeTabStatus = (typeof lifeTabStatuses)[number];

export const lifeSources = ["user", "ai", "voice", "scan"] as const;
export type LifeSource = (typeof lifeSources)[number];

export const lifeLayouts = ["timeline", "cards", "chart", "checklist", "gallery"] as const;
export type LifeLayout = (typeof lifeLayouts)[number];

export const lifeTabs = pgTable(
  "life_tabs",
  {
    id: uuid("id").primaryKey().defaultRandom(),
    userId: uuid("user_id")
      .notNull()
      .references(() => users.id, { onDelete: "cascade" }),
    clientTabId: text("client_tab_id").notNull(),
    displayName: varchar("display_name", { length: 120 }).notNull(),
    tabType: varchar("tab_type", { length: 60 }).notNull(),
    layout: varchar("layout", { length: 20 }).notNull().default("timeline"),
    secondaryLayout: varchar("secondary_layout", { length: 20 }),
    icon: varchar("icon", { length: 60 }).notNull().default("sparkles-outline"),
    color: varchar("color", { length: 20 }).notNull().default("#EE6A5E"),
    purpose: text("purpose"),
    // Field schema (LifeTabSchema) stored as-is; the device owns its shape.
    schema: jsonb("schema").notNull(),
    settings: jsonb("settings").default({}).notNull(),
    position: integer("position").default(0).notNull(),
    status: varchar("status", { length: 20 }).notNull().default("active"),
    source: varchar("source", { length: 20 }).notNull().default("user"),
    // Device timestamps (epoch ms) preserved so ordering survives a round-trip.
    clientCreatedAt: timestamp("client_created_at", { withTimezone: true }),
    clientUpdatedAt: timestamp("client_updated_at", { withTimezone: true }),
    createdAt: timestamp("created_at").defaultNow().notNull(),
    updatedAt: timestamp("updated_at").defaultNow().notNull(),
    deletedAt: timestamp("deleted_at"),
  },
  (table) => ({
    userClientUniq: uniqueIndex("life_tab_user_client_idx").on(table.userId, table.clientTabId),
    userIdIdx: index("life_tab_user_id_idx").on(table.userId),
    updatedAtIdx: index("life_tab_updated_at_idx").on(table.updatedAt),
  }),
);

export const lifeEntries = pgTable(
  "life_entries",
  {
    id: uuid("id").primaryKey().defaultRandom(),
    userId: uuid("user_id")
      .notNull()
      .references(() => users.id, { onDelete: "cascade" }),
    clientEntryId: text("client_entry_id").notNull(),
    // Relationship is by device tab id (the device owns referential integrity);
    // no FK so an entry can arrive before/after its tab during sync.
    clientTabId: text("client_tab_id").notNull(),
    // Validated key/values for the entry (against the tab's schema on-device).
    data: jsonb("data").notNull(),
    occurredAt: timestamp("occurred_at", { withTimezone: true }).notNull(),
    source: varchar("source", { length: 20 }).notNull().default("user"),
    rawInput: text("raw_input"),
    // Linked reminder (device reminder id) when an entry spawned one.
    reminderId: text("reminder_id"),
    clientCreatedAt: timestamp("client_created_at", { withTimezone: true }),
    clientUpdatedAt: timestamp("client_updated_at", { withTimezone: true }),
    createdAt: timestamp("created_at").defaultNow().notNull(),
    updatedAt: timestamp("updated_at").defaultNow().notNull(),
    deletedAt: timestamp("deleted_at"),
  },
  (table) => ({
    userClientUniq: uniqueIndex("life_entry_user_client_idx").on(table.userId, table.clientEntryId),
    userTabIdx: index("life_entry_user_tab_idx").on(table.userId, table.clientTabId),
    occurredAtIdx: index("life_entry_occurred_at_idx").on(table.occurredAt),
    updatedAtIdx: index("life_entry_updated_at_idx").on(table.updatedAt),
  }),
);

export type LifeTabRow = typeof lifeTabs.$inferSelect;
export type NewLifeTabRow = typeof lifeTabs.$inferInsert;
export type LifeEntryRow = typeof lifeEntries.$inferSelect;
export type NewLifeEntryRow = typeof lifeEntries.$inferInsert;
