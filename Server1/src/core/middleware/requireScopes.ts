import type { NextFunction, Request, Response } from "express";
import { ForbiddenError } from "../errors/index.js";

export const requireScopes =
  (scopes: string[]) =>
  (req: Request, _res: Response, next: NextFunction) => {
    const granted = req.auth?.token.scopes ?? [];
    const hasAllScopes = scopes.every((scope) => granted.includes(scope));

    if (!hasAllScopes) {
      next(new ForbiddenError("Missing required scope"));
      return;
    }

    next();
  };
