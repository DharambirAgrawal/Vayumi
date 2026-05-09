import { createPrivateKey, createPublicKey } from "node:crypto";
import { env } from "./index.js";

const normalizePem = (value: string) => value.replace(/\\n/g, "\n");
const decodePem = (value: string) => {
  const normalized = normalizePem(value).trim();
  return normalized.includes("BEGIN ")
    ? normalized
    : Buffer.from(normalized, "base64").toString("utf8").trim();
};

const parseKey = (value: string, type: "private" | "public") => {
  const pem = decodePem(value);

  try {
    return type === "private" ? createPrivateKey(pem) : createPublicKey(pem);
  } catch (error) {
    throw new Error(
      `Invalid JWT_${type.toUpperCase()}_KEY. Expected an RSA PEM key or base64-encoded PEM for RS256.`,
      { cause: error },
    );
  }
};

export const jwtConfig = {
  algorithm: "RS256" as const,
  privateKey: parseKey(env.JWT_PRIVATE_KEY, "private"),
  publicKey: parseKey(env.JWT_PUBLIC_KEY, "public"),
  accessExpiry: env.JWT_ACCESS_EXPIRY,
  refreshExpiry: env.JWT_REFRESH_EXPIRY,
};
