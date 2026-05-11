export const RedisKeys = {
  tokenBlocklist: (jti: string) => `blocklist:${jti}`,
  refreshToken: (sessionId: string) => `refresh:${sessionId}`,
  rateLimitIP: (ip: string) => `rl:ip:${ip}`,
  rateLimitUser: (userId: string) => `rl:user:${userId}`,
  passwordReset: (token: string) => `reset:${token}`,
  emailVerification: (token: string) => `verify:${token}`,
  userProfile: (userId: string) => `user:${userId}:profile`,
  userSessions: (userId: string) => `user:${userId}:sessions`,
  userSettings: (userId: string) => `user:${userId}:settings`,
  integrationOAuthState: (state: string) => `integration:state:${state}`,
};

export const RedisTTL = {
  accessToken: 15 * 60,
  refreshToken: 90 * 24 * 60 * 60,
  passwordReset: 15 * 60,
  emailVerification: 24 * 60 * 60,
  oauthState: 10 * 60,
  userProfile: 5 * 60,
  userSessions: 2 * 60,
  userSettings: 5 * 60,
};
