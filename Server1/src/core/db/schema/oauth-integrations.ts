import {
  boolean,
  index,
  jsonb,
  pgTable,
  text,
  timestamp,
  uniqueIndex,
  uuid,
  varchar,
} from "drizzle-orm/pg-core";
import { users } from "./users.js";

export const oauthIntegrations = pgTable(
  "oauth_integrations",
  {
    id: uuid("id").primaryKey().defaultRandom(),
    userId: uuid("user_id")
      .notNull()
      .references(() => users.id, { onDelete: "cascade" }),
    provider: varchar("provider", { length: 30 }).notNull(),
    providerAccountId: text("provider_account_id").notNull(),
    accessToken: text("access_token"),
    refreshToken: text("refresh_token"),
    accessTokenExpiresAt: timestamp("access_token_expires_at"),
    scopes: text("scopes"),
    syncState: jsonb("sync_state").$type<Record<string, unknown>>().default({}).notNull(),
    webhookActive: boolean("webhook_active").default(false).notNull(),
    webhookResourceId: text("webhook_resource_id"),
    webhookExpiresAt: timestamp("webhook_expires_at"),
    createdAt: timestamp("created_at").defaultNow().notNull(),
    updatedAt: timestamp("updated_at").defaultNow().notNull(),
  },
  (t) => ({
    userProviderUniq: uniqueIndex("oi_user_provider_idx").on(t.userId, t.provider),
  }),
);

export type OauthIntegration = typeof oauthIntegrations.$inferSelect;
export type NewOauthIntegration = typeof oauthIntegrations.$inferInsert;
