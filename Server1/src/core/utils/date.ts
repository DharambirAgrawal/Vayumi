const durationPattern = /^(\d+)([smhd])$/;

export const secondsFromDuration = (duration: string): number => {
  const match = duration.match(durationPattern);
  if (!match) {
    throw new Error(`Unsupported duration: ${duration}`);
  }

  const value = Number(match[1]);
  const unit = match[2];
  const multiplier = unit === "s" ? 1 : unit === "m" ? 60 : unit === "h" ? 3600 : 86400;
  return value * multiplier;
};

export const addSeconds = (date: Date, seconds: number) => new Date(date.getTime() + seconds * 1000);

export const isExpired = (date: Date) => date.getTime() <= Date.now();
