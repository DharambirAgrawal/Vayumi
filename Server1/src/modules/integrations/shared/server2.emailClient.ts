import { integrationsConfig } from "../../../core/config/integrations.js";
import { fetchWithRetries } from "../../../core/utils/fetchRetry.js";
import { signInternalServiceJwt } from "../../../core/utils/jwt.js";
import { SERVER2_CLASSIFY_FETCH, SERVER2_NOTIFY_FETCH } from "./email.constants.js";
import type { EmailCategory, EmailClassifyResult } from "./email.types.js";

export type ClassifyEmailRequest = {
  messageId: string;
  subject: string | null;
  snippet: string | null;
  fromEmail: string | null;
  fromName: string | null;
  body: string | null;
};

const authHeaders = () => ({
  Authorization: `Bearer ${signInternalServiceJwt()}`,
  "Content-Type": "application/json",
});

const parseClassifyResponse = (body: unknown): EmailClassifyResult | null => {
  if (!body || typeof body !== "object") {
    return null;
  }
  const record = body as Record<string, unknown>;
  const category = record.category;
  if (typeof category !== "string") {
    return null;
  }

  const keywords = Array.isArray(record.keywords)
    ? record.keywords.filter((k): k is string => typeof k === "string")
    : [];
  const summary = typeof record.summary === "string" ? record.summary : "";
  const priorityScore =
    typeof record.priorityScore === "number" && Number.isFinite(record.priorityScore)
      ? Math.round(record.priorityScore)
      : 5;

  return {
    category: category as EmailCategory,
    keywords,
    summary,
    priorityScore,
  };
};

const classifyUrl = () => `${integrationsConfig.server2InternalBaseUrl}/internal/emails/classify`;
const notifyUrl = () => `${integrationsConfig.server2InternalBaseUrl}/internal/emails/notify`;

export const server2EmailClient = {
  isConfigured: () => Boolean(integrationsConfig.server2InternalBaseUrl),

  async classifyEmail(input: ClassifyEmailRequest): Promise<EmailClassifyResult | null> {
    if (!integrationsConfig.server2InternalBaseUrl) {
      return null;
    }

    try {
      const response = await fetchWithRetries(
        classifyUrl(),
        {
          method: "POST",
          headers: authHeaders(),
          body: JSON.stringify(input),
        },
        {
          timeoutMs: integrationsConfig.emailAiClassifyTimeoutMs,
          attempts: SERVER2_CLASSIFY_FETCH.attempts,
          backoffMs: SERVER2_CLASSIFY_FETCH.backoffMs,
        },
      );

      if (!response.ok) {
        return null;
      }

      const json: unknown = await response.json();
      return parseClassifyResponse(json);
    } catch {
      return null;
    }
  },

  async notifyEmailDelivered(input: {
    userId: string;
    emailId: string;
    category: string;
    priorityScore: number | null;
    summary: string;
    fromName: string | null;
    fromEmail: string | null;
    subject: string | null;
  }): Promise<boolean> {
    if (!integrationsConfig.server2InternalBaseUrl) {
      return false;
    }

    try {
      const response = await fetchWithRetries(
        notifyUrl(),
        {
          method: "POST",
          headers: authHeaders(),
          body: JSON.stringify(input),
        },
        {
          timeoutMs: integrationsConfig.emailNotifyTimeoutMs,
          attempts: SERVER2_NOTIFY_FETCH.attempts,
          backoffMs: SERVER2_NOTIFY_FETCH.backoffMs,
        },
      );

      if (!response.ok) {
        return false;
      }

      const json: unknown = await response.json();
      if (!json || typeof json !== "object") {
        return false;
      }
      const handled = (json as { handled?: unknown }).handled;
      return handled === true;
    } catch {
      return false;
    }
  },
};
