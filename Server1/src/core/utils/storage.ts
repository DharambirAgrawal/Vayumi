import { createClient } from "@supabase/supabase-js";
import { env } from "../config/index.js";

const supabase = createClient(env.SUPABASE_URL, env.SUPABASE_SERVICE_ROLE_KEY, {
  auth: { persistSession: false },
});

const publicBaseUrl = (env.SUPABASE_STORAGE_PUBLIC_URL ||
  `${env.SUPABASE_URL.replace(/\/$/, "")}/storage/v1/object/public/${env.SUPABASE_STORAGE_BUCKET}`).replace(
  /\/$/,
  "",
);

/**
 * Object keys within the single storage bucket. Each method owns one category's
 * prefix, so new file types are added here (e.g. `cover`) rather than by adding
 * new buckets or scattering prefix strings across services.
 */
export const StorageKeys = {
  avatar: (userId: string, filename: string) => `avatars/${userId}/${filename}`,
} as const;

export const uploadPublicFile = async (input: {
  key: string;
  body: Buffer;
  contentType?: string | undefined;
}) => {
  const { error } = await supabase.storage.from(env.SUPABASE_STORAGE_BUCKET).upload(input.key, input.body, {
    upsert: true,
    ...(input.contentType ? { contentType: input.contentType } : {}),
  });

  if (error) {
    throw new Error(`Avatar upload failed: ${error.message}`);
  }

  return `${publicBaseUrl}/${input.key}`;
};
