import { createCipheriv, createDecipheriv, createHash, randomBytes } from "node:crypto";
import bcrypt from "bcryptjs";
import { env } from "../config/index.js";

const BCRYPT_ROUNDS = 12;

const getEncryptionKey = () => {
  const key = Buffer.from(env.ENCRYPTION_KEY, "base64");
  if (key.length === 32) {
    return key;
  }
  return createHash("sha256").update(env.ENCRYPTION_KEY).digest();
};

export const hashPassword = (value: string) => bcrypt.hash(value, BCRYPT_ROUNDS);
export const compareHash = (value: string, hash: string) => bcrypt.compare(value, hash);

export const sha256 = (value: string) => createHash("sha256").update(value).digest("hex");

export const randomToken = (bytes = 32) => randomBytes(bytes).toString("base64url");

export const encrypt = (plainText: string): string => {
  const iv = randomBytes(12);
  const cipher = createCipheriv("aes-256-gcm", getEncryptionKey(), iv);
  const encrypted = Buffer.concat([cipher.update(plainText, "utf8"), cipher.final()]);
  const authTag = cipher.getAuthTag();
  return `${iv.toString("base64url")}.${authTag.toString("base64url")}.${encrypted.toString("base64url")}`;
};

export const decrypt = (payload: string): string => {
  const [iv, authTag, encrypted] = payload.split(".");
  if (!iv || !authTag || !encrypted) {
    throw new Error("Invalid encrypted payload");
  }

  const decipher = createDecipheriv("aes-256-gcm", getEncryptionKey(), Buffer.from(iv, "base64url"));
  decipher.setAuthTag(Buffer.from(authTag, "base64url"));
  return Buffer.concat([
    decipher.update(Buffer.from(encrypted, "base64url")),
    decipher.final(),
  ]).toString("utf8");
};
