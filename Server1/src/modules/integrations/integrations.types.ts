export type ConnectedIntegrationDto = {
  id: string;
  provider: string;
  providerAccountId: string;
  syncState: Record<string, unknown>;
  webhookActive: boolean;
  webhookExpiresAt: Date | null;
  createdAt: Date;
  updatedAt: Date;
};
