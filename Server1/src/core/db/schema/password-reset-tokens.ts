import { index, integer, pgTable, text, timestamp, uuid } from "drizzle-orm/pg-core";
import { users } from "./users.js";

export const passwordResetTokens = pgTable(
  "password_reset_tokens",
  {
    id: uuid("id").primaryKey().defaultRandom(),
    userId: uuid("user_id")
      .notNull()
      .references(() => users.id, { onDelete: "cascade" }),
    tokenHash: text("token_hash").notNull(),
    expiresAt: timestamp("expires_at").notNull(),
    usedAt: timestamp("used_at"),
    attempts: integer("attempts").notNull().default(0),
    createdAt: timestamp("created_at").defaultNow().notNull(),
  },
  (table) => ({
    userIdIdx: index("prt_user_id_idx").on(table.userId),
    tokenHashIdx: index("prt_token_hash_idx").on(table.tokenHash),
    expiryIdx: index("prt_expires_at_idx").on(table.expiresAt),
  }),
);

export type PasswordResetToken = typeof passwordResetTokens.$inferSelect;
export type NewPasswordResetToken = typeof passwordResetTokens.$inferInsert;
