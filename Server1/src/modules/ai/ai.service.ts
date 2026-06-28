import { appConfig } from "../../core/config/app.js";
import { AppError } from "../../core/errors/index.js";
import { fetchWithTimeout } from "../../core/utils/fetchRetry.js";
import { logger } from "../../core/utils/logger.js";
import { configuredEndpointCount, configuredProviderIds, endpointChain } from "./ai.providers.js";
import type { ChatRequestInput } from "./ai.validators.js";

const { ai: aiLimits } = appConfig.limits;

const isToolUseFailure = (body: string): boolean =>
  /tool_use_failed|failed to call a function|"function"/i.test(body);

export const aiService = {
  /** Configured providers + total endpoints + the per-user limits, for the app. */
  status() {
    return {
      providers: configuredProviderIds(),
      endpoints: configuredEndpointCount(),
      daily_limit: aiLimits.dailyLimit,
      minute_limit: aiLimits.minuteLimit,
    };
  },

  /**
   * Forward an OpenAI-compatible chat completion to the first working endpoint.
   * Since rate limits are per-model, the chain walks model-by-model (each its own
   * quota) then provider-by-provider, failing over on 429 / tool_use_failed / 5xx /
   * network. Returns the upstream completion JSON unchanged (so the app's tool loop
   * reads choices[0].message) plus which provider:model served it. Never leaks keys.
   */
  async chat(input: ChatRequestInput): Promise<{ body: unknown; provider: string }> {
    const chain = endpointChain(input.provider);
    if (chain.length === 0) {
      throw new AppError(503, "AI_UNAVAILABLE", "No cloud AI provider is configured.");
    }

    let lastReason = "no endpoints tried";

    for (const endpoint of chain) {
      const payload = JSON.stringify({
        model: endpoint.model,
        messages: input.messages,
        ...(input.tools ? { tools: input.tools, tool_choice: input.tool_choice ?? "auto" } : {}),
        temperature: input.temperature ?? 0.4,
        max_tokens: Math.min(input.max_tokens ?? 1024, aiLimits.maxOutputTokens),
      });

      let res: Response;
      try {
        res = await fetchWithTimeout(
          `${endpoint.baseUrl}/chat/completions`,
          {
            method: "POST",
            headers: {
              "Content-Type": "application/json",
              Authorization: `Bearer ${endpoint.apiKey}`,
            },
            body: payload,
          },
          aiLimits.requestTimeoutMs,
        );
      } catch (error) {
        lastReason = error instanceof Error ? `${endpoint.label}: ${error.message}` : `${endpoint.label}: network`;
        logger.warn({ endpoint: endpoint.label }, "AI endpoint request failed, failing over");
        continue;
      }

      if (res.status === 429 || res.status >= 500) {
        lastReason = `${endpoint.label}: HTTP ${res.status}`;
        logger.warn({ endpoint: endpoint.label, status: res.status }, "AI endpoint unavailable, failing over");
        continue;
      }

      if (res.status === 400) {
        const text = await res.text().catch(() => "");
        if (isToolUseFailure(text)) {
          lastReason = `${endpoint.label}: tool_use_failed`;
          logger.warn({ endpoint: endpoint.label }, "AI endpoint tool_use_failed, failing over");
          continue;
        }
        // A genuine bad request (not transient) — surface without provider detail.
        throw new AppError(400, "AI_BAD_REQUEST", "The AI request was rejected.");
      }

      if (!res.ok) {
        lastReason = `${endpoint.label}: HTTP ${res.status}`;
        continue;
      }

      const body = (await res.json().catch(() => null)) as unknown;
      if (!body) {
        lastReason = `${endpoint.label}: invalid JSON`;
        continue;
      }
      return { body, provider: endpoint.label };
    }

    logger.warn({ reason: lastReason }, "All AI endpoints exhausted");
    throw new AppError(503, "AI_UNAVAILABLE", "The cloud AI is busy right now. Please try again.");
  },
};
