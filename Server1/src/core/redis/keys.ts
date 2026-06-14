export const RedisKeys = {
  tokenBlocklist: (jti: string) => `blocklist:${jti}`,
  refreshToken: (sessionId: string) => `refresh:${sessionId}`,
  rateLimitIP: (ip: string) => `rl:ip:${ip}`,
  rateLimitUser: (userId: string) => `rl:user:${userId}`,
  passwordReset: (token: string) => `reset:${token}`,
  emailVerificationCooldown: (userId: string) => `verify:cooldown:${userId}`,
  userProfile: (userId: string) => `user:${userId}:profile`,
  userSessions: (userId: string) => `user:${userId}:sessions`,
  userSettings: (userId: string) => `user:${userId}:settings`,
  emailSyncLock: (userId: string, provider: string) => `sync:lock:${userId}:${provider}`,
  integrationOAuthState: (state: string) => `integration:state:${state}`,
  reminderFireLock: () => "reminder:fire:lock",
};

export const RedisTTL = {
  accessToken: 15 * 60,
  refreshToken: 90 * 24 * 60 * 60,
  passwordReset: 15 * 60,
  emailVerificationCode: 10 * 60,
  emailVerificationCooldown: 60,
  oauthState: 10 * 60,
  emailSyncLock: 5 * 60,
  userProfile: 5 * 60,
  userSessions: 2 * 60,
  userSettings: 5 * 60,
  reminderFireLock: 55,
};
