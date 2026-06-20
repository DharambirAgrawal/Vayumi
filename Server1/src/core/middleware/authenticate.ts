import type { NextFunction, Request, Response } from "express";
import { and, eq, isNull } from "drizzle-orm";
import { db } from "../db/index.js";
import { sessions, users } from "../db/schema/index.js";
import { AuthError } from "../errors/index.js";
import { verifyAccessToken } from "../utils/jwt.js";

export const authenticate = async (req: Request, _res: Response, next: NextFunction) => {
  try {
    const header = req.header("authorization");
    const [scheme, token] = header?.split(" ") ?? [];

    if (scheme !== "Bearer" || !token) {
      throw new AuthError("Missing bearer token");
    }

    const payload = verifyAccessToken(token);

    const [session] = await db
      .select()
      .from(sessions)
      .where(and(eq(sessions.id, payload.sid), eq(sessions.isActive, true), isNull(sessions.revokedAt)))
      .limit(1);

    if (!session || session.expiresAt <= new Date()) {
      throw new AuthError("Session is inactive");
    }

    if (session.userId !== payload.sub) {
      throw new AuthError("Token subject mismatch");
    }

    const [user] = await db
      .select()
      .from(users)
      .where(and(eq(users.id, payload.sub), isNull(users.deletedAt)))
      .limit(1);

    if (!user) {
      throw new AuthError("User is inactive");
    }

    req.auth = { user, session, token: payload };
    next();
  } catch (error) {
    next(error instanceof AuthError ? error : new AuthError("Invalid token"));
  }
};
