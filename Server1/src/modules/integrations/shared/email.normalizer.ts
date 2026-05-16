import type { EmailMessage, EmailProviderId } from "./email.types.js";

const isProvider = (value: string): value is EmailProviderId =>
  value === "gmail" || value === "outlook";

/** Builds a snippet for list UI when the provider only gives body text. */
export const truncateSnippet = (text: string | null | undefined, maxLen = 150): string | null => {
  if (!text) {
    return null;
  }
  const normalized = text.replace(/\s+/g, " ").trim();
  if (normalized.length <= maxLen) {
    return normalized;
  }
  return `${normalized.slice(0, maxLen - 1)}…`;
};

export type NormalizeEmailMessageInput = Omit<EmailMessage, "receivedAt"> & {
  receivedAt: Date | string;
};

export const normalizeEmailMessage = (input: NormalizeEmailMessageInput): EmailMessage => {
  const receivedAt =
    input.receivedAt instanceof Date ? input.receivedAt : new Date(input.receivedAt);
  if (Number.isNaN(receivedAt.getTime())) {
    throw new Error("Invalid receivedAt");
  }

  if (!isProvider(input.provider)) {
    throw new Error(`Unsupported provider: ${input.provider}`);
  }

  if (!input.providerMessageId?.trim()) {
    throw new Error("providerMessageId is required");
  }

  return {
    provider: input.provider,
    providerMessageId: input.providerMessageId.trim(),
    threadId: input.threadId ?? null,
    receivedAt,
    from: {
      email: input.from.email?.trim() || null,
      name: input.from.name?.trim() || null,
    },
    to: input.to ?? [],
    cc: input.cc ?? [],
    subject: input.subject ?? null,
    snippet: input.snippet ?? truncateSnippet(input.bodyText),
    bodyText: input.bodyText ?? null,
    isRead: Boolean(input.isRead),
    isStarred: Boolean(input.isStarred),
    hasAttachments: Boolean(input.hasAttachments),
    attachmentMeta: input.attachmentMeta ?? [],
    labels: input.labels ?? [],
  };
};
