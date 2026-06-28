import { boolean, index, pgTable, text, timestamp, uniqueIndex, uuid, varchar } from "drizzle-orm/pg-core";
import { users } from "./users.js";

// Curated long-term facts the assistant remembers about the user (preferences,
// routines, details). Tiny + capped on-device; synced idempotently on (user_id,
// key) — the key is the semantic identity, so the same fact merges across devices.
// Soft delete (deleted_at) so a "forget" propagates instead of resurrecting.

export const memorySources = ["user", "ai"] as const;
export type MemorySource = (typeof memorySources)[number];

export const memoryCategories = ["profile", "preference", "health", "routine", "misc"] as const;
export type MemoryCategory = (typeof memoryCategories)[number];

export const memoryFacts = pgTable(
  "memory_facts",
  {
    id: uuid("id").primaryKey().defaultRandom(),
    userId: uuid("user_id")
      .notNull()
      .references(() => users.id, { onDelete: "cascade" }),
    key: varchar("key", { length: 120 }).notNull(),
    value: text("value").notNull(),
    category: varchar("category", { length: 20 }).notNull().default("misc"),
    source: varchar("source", { length: 20 }).notNull().default("ai"),
    pinned: boolean("pinned").default(false).notNull(),
    clientUpdatedAt: timestamp("client_updated_at", { withTimezone: true }),
    createdAt: timestamp("created_at").defaultNow().notNull(),
    updatedAt: timestamp("updated_at").defaultNow().notNull(),
    deletedAt: timestamp("deleted_at"),
  },
  (table) => ({
    userKeyUniq: uniqueIndex("mem_user_key_idx").on(table.userId, table.key),
    userIdIdx: index("mem_fact_user_id_idx").on(table.userId),
    updatedAtIdx: index("mem_fact_updated_at_idx").on(table.updatedAt),
  }),
);

export type MemoryFactRow = typeof memoryFacts.$inferSelect;
export type NewMemoryFactRow = typeof memoryFacts.$inferInsert;
