import type { EmailMessage, EmailProviderId } from "./email.types.js";

export type ProviderSyncState = Record<string, unknown>;

export type FetchEmailDeltaResult = {
  messages: EmailMessage[];
  /** Merged into `oauth_integrations.sync_state` after a successful batch. */
  nextSyncState: ProviderSyncState;
};

/**
 * Provider-specific I/O (Gmail / Graph). Normalization to `EmailMessage` happens
 * inside the provider implementation so cron + webhooks share one contract.
 */
export interface IEmailProvider {
  readonly providerId: EmailProviderId;
  fetchDelta: (syncState: ProviderSyncState) => Promise<FetchEmailDeltaResult>;
  fetchBodyText: (providerMessageId: string) => Promise<string>;
  setReadState: (providerMessageId: string, isRead: boolean) => Promise<void>;
  setStarredState: (providerMessageId: string, isStarred: boolean) => Promise<void>;
}
