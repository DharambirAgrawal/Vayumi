import { env } from "../../core/config/index.js";

/**
 * Cloud LLM providers for the app's "Server" mode. All OpenAI-compatible. Keys live
 * ONLY here (server-side). Rate limits are PER MODEL, so each provider lists several
 * tool-capable models ordered best→fallback: when one model is rate-limited (429),
 * we move to the next model (its own quota), then the next provider. This multiplies
 * the free throughput. Every model here is verified to support function-calling.
 */

export type AiProviderId = "groq" | "cerebras" | "gemini";

interface ProviderDef {
  id: AiProviderId;
  baseUrl: string;
  apiKey: string | undefined;
  /** Ordered best → fallback; each model has its own rate limit. Tools-verified. */
  models: string[];
  vision: boolean;
}

const PROVIDERS: Record<AiProviderId, ProviderDef> = {
  groq: {
    id: "groq",
    baseUrl: "https://api.groq.com/openai/v1",
    apiKey: env.GROQ_API_KEY,
    models: [
      "meta-llama/llama-4-scout-17b-16e-instruct", // 30K TPM / 500K TPD — best capacity
      "openai/gpt-oss-120b", // 8K TPM / 200K TPD — strongest
      "openai/gpt-oss-20b", // 8K TPM / 200K TPD
      "llama-3.1-8b-instant", // 6K TPM / 500K TPD / 14.4K RPD — high volume, lighter
      "llama-3.3-70b-versatile", // 12K TPM / 100K TPD — last (occasionally flaky tools)
    ],
    vision: false,
  },
  cerebras: {
    id: "cerebras",
    baseUrl: "https://api.cerebras.ai/v1",
    apiKey: env.CEREBRAS_API_KEY,
    models: ["gpt-oss-120b", "zai-glm-4.7"],
    vision: false,
  },
  gemini: {
    id: "gemini",
    baseUrl: "https://generativelanguage.googleapis.com/v1beta/openai",
    apiKey: env.GEMINI_API_KEY,
    models: ["gemini-2.0-flash"],
    vision: true,
  },
};

/** One concrete (provider, model) target. */
export interface AiEndpoint {
  providerId: AiProviderId;
  baseUrl: string;
  apiKey: string;
  model: string;
  /** "groq:llama-4-scout" for the X-AI-Provider header / logs. */
  label: string;
}

const ORDER: AiProviderId[] = ["groq", "cerebras", "gemini"];

export const isConfigured = (id: AiProviderId): boolean => Boolean(PROVIDERS[id].apiKey);

export const configuredProviderIds = (): AiProviderId[] => ORDER.filter(isConfigured);

/**
 * Flat fallback chain of every (provider, model) endpoint that has a key —
 * the caller's preferred provider's models first, then the rest. Failover walks
 * this list on 429 / tool_use_failed / 5xx / network.
 */
export const endpointChain = (preferred?: AiProviderId): AiEndpoint[] => {
  const order = preferred ? [preferred, ...ORDER] : ORDER;
  const seen = new Set<AiProviderId>();
  const chain: AiEndpoint[] = [];
  for (const id of order) {
    if (seen.has(id) || !isConfigured(id)) continue;
    seen.add(id);
    const p = PROVIDERS[id];
    for (const model of p.models) {
      chain.push({ providerId: id, baseUrl: p.baseUrl, apiKey: p.apiKey!, model, label: `${id}:${model}` });
    }
  }
  return chain;
};

/** Total tool-capable endpoints available right now (for status). */
export const configuredEndpointCount = (): number => endpointChain().length;
