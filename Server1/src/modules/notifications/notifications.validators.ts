import { z } from "zod";
import { pushPlatforms } from "../../core/types/index.js";

export const registerPushTokenSchema = z.object({
  token: z.string().min(1).max(4096),
  platform: z.enum(pushPlatforms),
});

export const removePushTokenSchema = z.object({
  token: z.string().min(1).max(4096),
});

export type RegisterPushTokenInput = z.infer<typeof registerPushTokenSchema>;
export type RemovePushTokenInput = z.infer<typeof removePushTokenSchema>;
