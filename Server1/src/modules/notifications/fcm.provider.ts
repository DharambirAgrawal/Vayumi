import { readFile } from "node:fs/promises";
import { GoogleAuth } from "google-auth-library";
import { env } from "../../core/config/index.js";
import { logger } from "../../core/utils/logger.js";

type ServiceAccount = {
  project_id: string;
  client_email: string;
  private_key: string;
};

let cachedAuth: GoogleAuth | null = null;
let cachedProjectId: string | null = null;

const loadServiceAccount = async (): Promise<ServiceAccount> => {
  const raw = await readFile(env.FCM_SERVICE_ACCOUNT_PATH, "utf8");
  return JSON.parse(raw) as ServiceAccount;
};

const getAuth = async () => {
  if (!cachedAuth) {
    const credentials = await loadServiceAccount();
    cachedProjectId = credentials.project_id;
    cachedAuth = new GoogleAuth({
      credentials,
      scopes: ["https://www.googleapis.com/auth/firebase.messaging"],
    });
  }

  return cachedAuth;
};

export const fcmProvider = {
  async sendPush(input: { token: string; title: string; body: string; data?: Record<string, string> }) {
    try {
      const auth = await getAuth();
      const client = await auth.getClient();
      const accessToken = await client.getAccessToken();

      if (!accessToken.token || !cachedProjectId) {
        return { success: false as const, error: "FCM auth failed" };
      }

      const response = await fetch(
        `https://fcm.googleapis.com/v1/projects/${cachedProjectId}/messages:send`,
        {
          method: "POST",
          headers: {
            Authorization: `Bearer ${accessToken.token}`,
            "Content-Type": "application/json",
          },
          body: JSON.stringify({
            message: {
              token: input.token,
              notification: {
                title: input.title,
                body: input.body,
              },
              data: input.data,
            },
          }),
        },
      );

      if (!response.ok) {
        const errorBody = await response.text();
        logger.warn({ status: response.status, errorBody }, "FCM send failed");
        return { success: false as const, error: "FCM send failed" };
      }

      return { success: true as const };
    } catch (error) {
      logger.error({ error }, "FCM send error");
      return { success: false as const, error: "FCM send error" };
    }
  },
};
