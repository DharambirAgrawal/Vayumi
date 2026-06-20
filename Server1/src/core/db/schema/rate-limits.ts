import { index, integer, pgTable, text, timestamp } from "drizzle-orm/pg-core";

export const rateLimits = pgTable(
  "rate_limits",
  {
    key: text("key").primaryKey(),
    count: integer("count").notNull().default(0),
    expiresAt: timestamp("expires_at").notNull(),
  },
  (table) => ({
    expiryIdx: index("rate_limits_expires_at_idx").on(table.expiresAt),
  }),
);

export type RateLimit = typeof rateLimits.$inferSelect;
export type NewRateLimit = typeof rateLimits.$inferInsert;
