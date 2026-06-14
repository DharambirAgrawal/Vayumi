import type { AuthContext } from "./index.js";

declare global {
  namespace Express {
    interface Request {
      auth?: AuthContext;
      internalService?: boolean;
    }
  }
}

export {};
