import { asc, eq } from "drizzle-orm";
import { db } from "../../core/db/index.js";
import { oauthIntegrations } from "../../core/db/schema/oauth-integrations.js";
import type { ConnectedIntegrationDto } from "./integrations.types.js";

export const integrationsService = {
  async listForUser(userId: string): Promise<ConnectedIntegrationDto[]> {
    const rows = await db
      .select({
        id: oauthIntegrations.id,
        provider: oauthIntegrations.provider,
        providerAccountId: oauthIntegrations.providerAccountId,
        syncState: oauthIntegrations.syncState,
        webhookActive: oauthIntegrations.webhookActive,
        webhookExpiresAt: oauthIntegrations.webhookExpiresAt,
        createdAt: oauthIntegrations.createdAt,
        updatedAt: oauthIntegrations.updatedAt,
      })
      .from(oauthIntegrations)
      .where(eq(oauthIntegrations.userId, userId))
      .orderBy(asc(oauthIntegrations.createdAt));

    return rows.map((row) => ({
      ...row,
      syncState: row.syncState ?? {},
    }));
  },
};
