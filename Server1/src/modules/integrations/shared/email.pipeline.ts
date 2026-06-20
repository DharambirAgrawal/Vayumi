import { eq } from "drizzle-orm";
import { db } from "../../../core/db/index.js";
import { syncedEmails } from "../../../core/db/schema/synced-emails.js";
import { logger } from "../../../core/utils/logger.js";
import { isUniqueViolation } from "../../../core/utils/postgres.js";
import { EMAIL_CLASSIFY_MAX_BODY_CHARS } from "./email.constants.js";
import { MaskingSession } from "./email.masker.js";
import { server2EmailClient } from "./server2.emailClient.js";
import type { EmailCategory, EmailClassifyResult, EmailMessage, ProcessIncomingEmailOutcome } from "./email.types.js";
import { isDiscardCategory } from "./email.types.js";

const AI_CATEGORIES: readonly EmailCategory[] = [
  "marketing",
  "spam",
  "transactional",
  "informational",
  "action_required",
  "urgent",
];

const normalizeCategory = (value: string): EmailCategory =>
  AI_CATEGORIES.includes(value as EmailCategory) ? (value as EmailCategory) : "informational";

const sliceBodyForClassify = (body: string | null): string | null => {
  if (!body) {
    return null;
  }
  const max = EMAIL_CLASSIFY_MAX_BODY_CHARS;
  return body.length <= max ? body : body.slice(0, max);
};

const applyClassifyOrFallback = (
  raw: EmailClassifyResult | null,
): { result: EmailClassifyResult; aiProcessed: boolean } => {
  if (!raw) {
    return {
      aiProcessed: false,
      result: {
        category: "informational",
        keywords: [],
        summary: "",
        priorityScore: 5,
      },
    };
  }

  const normalized: EmailClassifyResult = {
    ...raw,
    category: normalizeCategory(String(raw.category)),
    keywords: Array.isArray(raw.keywords) ? raw.keywords.filter((k) => typeof k === "string") : [],
    summary: typeof raw.summary === "string" ? raw.summary : "",
    priorityScore: Number.isFinite(raw.priorityScore) ? Math.round(raw.priorityScore) : 5,
  };

  return { aiProcessed: true, result: normalized };
};

const buildInsertValues = (input: {
  userId: string;
  message: EmailMessage;
  classify: EmailClassifyResult;
  aiProcessed: boolean;
  keywords: string[];
}) => ({
  userId: input.userId,
  provider: input.message.provider,
  providerMessageId: input.message.providerMessageId,
  threadId: input.message.threadId,
  fromEmail: input.message.from.email,
  fromName: input.message.from.name,
  to: input.message.to,
  cc: input.message.cc,
  subject: input.message.subject,
  snippet: input.message.snippet,
  summary: input.classify.summary,
  keywords: input.keywords,
  category: input.classify.category,
  priorityScore: input.classify.priorityScore,
  isRead: input.message.isRead,
  isStarred: input.message.isStarred,
  hasAttachments: input.message.hasAttachments,
  attachmentMeta: input.message.attachmentMeta,
  labels: input.message.labels,
  aiProcessed: input.aiProcessed,
  receivedAt: input.message.receivedAt,
});

export const processIncomingEmail = async (params: {
  userId: string;
  message: EmailMessage;
}): Promise<ProcessIncomingEmailOutcome> => {
  const { userId, message } = params;
  const session = new MaskingSession();

  const maskedSubject = session.maskEmailsInText(message.subject ?? "");
  const maskedSnippet = session.maskEmailsInText(message.snippet ?? "");
  const maskedBody = session.maskEmailsInText(sliceBodyForClassify(message.bodyText) ?? "");
  const maskedFromEmail = message.from.email ? session.maskEmailsInText(message.from.email) : null;
  const maskedFromName = session.maskDisplayName(message.from.name);

  const classifyRaw = await server2EmailClient.classifyEmail({
    messageId: message.providerMessageId,
    subject: maskedSubject || null,
    snippet: maskedSnippet || null,
    fromEmail: maskedFromEmail,
    fromName: maskedFromName,
    body: maskedBody || null,
  });

  const { result: classified, aiProcessed } = applyClassifyOrFallback(classifyRaw);

  if (isDiscardCategory(classified.category)) {
    return { status: "discarded", reason: "category" };
  }

  const keywords = session.unmaskStrings(classified.keywords);

  try {
    const [inserted] = await db
      .insert(syncedEmails)
      .values(
        buildInsertValues({
          userId,
          message,
          classify: classified,
          aiProcessed,
          keywords,
        }),
      )
      .returning({ id: syncedEmails.id });

    if (!inserted) {
      logger.error({ userId, provider: message.provider }, "synced_emails insert returned no row");
      return { status: "duplicate" };
    }

    const handled = await server2EmailClient.notifyEmailDelivered({
      userId,
      emailId: inserted.id,
      category: classified.category,
      priorityScore: classified.priorityScore,
      summary: classified.summary,
      fromName: message.from.name,
      fromEmail: message.from.email,
      subject: message.subject,
    });

    await db
      .update(syncedEmails)
      .set({
        agentDelivered: handled,
        notificationFallback: !handled,
      })
      .where(eq(syncedEmails.id, inserted.id));

    return { status: "saved", emailId: inserted.id, aiProcessed };
  } catch (error) {
    if (isUniqueViolation(error)) {
      return { status: "duplicate" };
    }
    throw error;
  }
};
