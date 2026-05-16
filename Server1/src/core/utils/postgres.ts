export const isUniqueViolation = (error: unknown): boolean => readPgErrorCode(error) === "23505";

export const readPgErrorCode = (error: unknown): string | undefined => {
  if (!error || typeof error !== "object") {
    return undefined;
  }
  const direct = (error as { code?: unknown }).code;
  if (typeof direct === "string") {
    return direct;
  }
  const cause = (error as { cause?: unknown }).cause;
  if (cause && typeof cause === "object") {
    const nested = (cause as { code?: unknown }).code;
    if (typeof nested === "string") {
      return nested;
    }
  }
  return undefined;
};
