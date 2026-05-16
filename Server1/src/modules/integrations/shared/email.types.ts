import type { SyncedEmailAttachmentMeta, SyncedEmailParty } from "../../../core/db/schema/synced-emails.js";

export const EMAIL_PROVIDER_IDS = ["gmail", "outlook"] as const;
export type EmailProviderId = (typeof EMAIL_PROVIDER_IDS)[number];

export type EmailCategory =
  | "marketing"
  | "spam"
  | "transactional"
  | "informational"
  | "action_required"
  | "urgent";

/** Categories dropped before persistence (see PLAN email pipeline). */
export const DISCARD_BEFORE_SAVE_CATEGORIES = ["marketing", "spam"] as const satisfies readonly EmailCategory[];

export type EmailMessage = {
  provider: EmailProviderId;
  providerMessageId: string;
  threadId: string | null;
  receivedAt: Date;
  from: { email: string | null; name: string | null };
  to: SyncedEmailParty[];
  cc: SyncedEmailParty[];
  subject: string | null;
  snippet: string | null;
  /** Plain text for classify — never stored in `synced_emails`. */
  bodyText: string | null;
  isRead: boolean;
  isStarred: boolean;
  hasAttachments: boolean;
  attachmentMeta: SyncedEmailAttachmentMeta[];
  labels: string[];
};

export type EmailClassifyResult = {
  category: EmailCategory;
  keywords: string[];
  summary: string;
  priorityScore: number;
};

export type ProcessIncomingEmailOutcome =
  | { status: "discarded"; reason: "category" }
  | { status: "duplicate" }
  | { status: "saved"; emailId: string; aiProcessed: boolean };

export const isDiscardCategory = (category: EmailCategory): boolean =>
  (DISCARD_BEFORE_SAVE_CATEGORIES as readonly string[]).includes(category);
