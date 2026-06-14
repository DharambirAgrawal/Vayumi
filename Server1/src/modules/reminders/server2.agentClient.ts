import { integrationsConfig } from "../../core/config/integrations.js";
import { remindersConfig } from "../../core/config/reminders.js";
import { fetchWithRetries } from "../../core/utils/fetchRetry.js";
import { signInternalServiceJwt } from "../../core/utils/jwt.js";
import { SERVER2_AGENT_EVENT_FETCH } from "./reminders.constants.js";
import type { AgentEventType } from "./reminders.types.js";

const authHeaders = () => ({
  Authorization: `Bearer ${signInternalServiceJwt()}`,
  "Content-Type": "application/json",
});

const agentEventUrl = () => `${integrationsConfig.server2InternalBaseUrl}/internal/agent/event`;

export const server2AgentClient = {
  isConfigured: () => Boolean(integrationsConfig.server2InternalBaseUrl),

  async sendAgentEvent(input: {
    type: AgentEventType;
    userId: string;
    payload: Record<string, unknown>;
  }): Promise<boolean> {
    if (!integrationsConfig.server2InternalBaseUrl) {
      return false;
    }

    try {
      const response = await fetchWithRetries(
        agentEventUrl(),
        {
          method: "POST",
          headers: authHeaders(),
          body: JSON.stringify(input),
        },
        {
          timeoutMs: remindersConfig.agentEventTimeoutMs,
          attempts: SERVER2_AGENT_EVENT_FETCH.attempts,
          backoffMs: SERVER2_AGENT_EVENT_FETCH.backoffMs,
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
