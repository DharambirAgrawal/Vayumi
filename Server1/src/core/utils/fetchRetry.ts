const sleep = (ms: number) => new Promise<void>((resolve) => setTimeout(resolve, ms));

export type FetchWithRetriesOptions = {
  timeoutMs: number;
  attempts: number;
  /** Backoff after attempt i (0-based) before retry i+1; last entry repeats if shorter than attempts-1. */
  backoffMs: readonly number[];
};

const pickBackoff = (backoffMs: readonly number[], attemptIndex: number) => {
  if (backoffMs.length === 0) {
    return 0;
  }
  return backoffMs[Math.min(attemptIndex, backoffMs.length - 1)] ?? 0;
};

export const fetchWithTimeout = async (
  url: string,
  init: RequestInit,
  timeoutMs: number,
): Promise<Response> => {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    return await fetch(url, { ...init, signal: controller.signal });
  } finally {
    clearTimeout(timer);
  }
};

/** Native fetch with per-attempt timeout and bounded retries (no deps). */
export const fetchWithRetries = async (
  url: string,
  init: RequestInit,
  options: FetchWithRetriesOptions,
): Promise<Response> => {
  let lastResponse: Response | undefined;
  let lastError: unknown;

  for (let attempt = 0; attempt < options.attempts; attempt++) {
    try {
      const response = await fetchWithTimeout(url, init, options.timeoutMs);
      lastResponse = response;
      if (response.ok) {
        return response;
      }
      lastError = new Error(`HTTP ${response.status}`);
    } catch (error) {
      lastError = error;
    }

    if (attempt < options.attempts - 1) {
      await sleep(pickBackoff(options.backoffMs, attempt));
    }
  }

  if (lastResponse) {
    return lastResponse;
  }

  throw lastError instanceof Error ? lastError : new Error(String(lastError));
};
