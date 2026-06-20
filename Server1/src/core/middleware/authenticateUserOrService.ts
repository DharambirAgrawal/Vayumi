import type { NextFunction, Request, Response } from "express";
import { and, eq, isNull } from "drizzle-orm";
import jwt from "jsonwebtoken";
import type { JwtPayload } from "jsonwebtoken";
import { jwtConfig } from "../config/jwt.js";
import { db } from "../db/index.js";
import { sessions, users } from "../db/schema/index.js";
import { AuthError } from "../errors/index.js";
import type { AccessTokenPayload } from "../types/index.js";

const isInternalServiceToken = (payload: JwtPayload): boolean =>
  payload.scope === "internal" && payload.iss === "server1";

export const authenticateUserOrService = async (req: Request, _res: Response, next: NextFunction) => {
  try {
    const header = req.header("authorization");
    const [scheme, token] = header?.split(" ") ?? [];

    if (scheme !== "Bearer" || !token) {
      throw new AuthError("Missing bearer token");
    }

    let payload: JwtPayload;
    try {
      payload = jwt.verify(token, jwtConfig.publicKey, {
        algorithms: [jwtConfig.algorithm],
      }) as JwtPayload;
    } catch {
      throw new AuthError("Invalid token");
    }

    if (isInternalServiceToken(payload)) {
      req.internalService = true;
      next();
      return;
    }

    const accessPayload = payload as AccessTokenPayload;
    if (!accessPayload.sub || !accessPayload.sid || !accessPayload.jti) {
      throw new AuthError("Invalid token");
    }

    const [session] = await db
      .select()
      .from(sessions)
      .where(
        and(eq(sessions.id, accessPayload.sid), eq(sessions.isActive, true), isNull(sessions.revokedAt)),
      )
      .limit(1);

    if (!session || session.expiresAt <= new Date()) {
      throw new AuthError("Session is inactive");
    }

    if (session.userId !== accessPayload.sub) {
      throw new AuthError("Token subject mismatch");
    }

    const [user] = await db
      .select()
      .from(users)
      .where(and(eq(users.id, accessPayload.sub), isNull(users.deletedAt)))
      .limit(1);

    if (!user) {
      throw new AuthError("User is inactive");
    }

    req.auth = { user, session, token: accessPayload };
    next();
  } catch (error) {
    next(error instanceof AuthError ? error : new AuthError("Invalid token"));
  }
};
