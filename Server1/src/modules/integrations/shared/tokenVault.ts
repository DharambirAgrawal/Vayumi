import { encrypt, decrypt } from "../../../core/utils/crypto.js";

/** Semantic alias for OAuth token encryption at rest (reuses `ENCRYPTION_KEY`). */
export const tokenVault = {
  seal: encrypt,
  unseal: decrypt,
};
