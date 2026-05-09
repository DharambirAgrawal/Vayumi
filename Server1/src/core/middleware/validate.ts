import type { NextFunction, Request, Response } from "express";
import type { ZodTypeAny } from "zod";
import { ValidationError } from "../errors/index.js";

const assignValidatedData = (req: Request, source: "body" | "params" | "query", data: unknown) => {
  if (source === "body") {
    req.body = data;
    return;
  }

  Object.assign(req[source], data);
};

const runValidation =
  (source: "body" | "params" | "query", schema: ZodTypeAny) =>
  (req: Request, _res: Response, next: NextFunction) => {
    const result = schema.safeParse(req[source]);
    if (!result.success) {
      next(new ValidationError("Validation failed", result.error.flatten()));
      return;
    }

    assignValidatedData(req, source, result.data);
    next();
  };

export const validate = {
  body: (schema: ZodTypeAny) => runValidation("body", schema),
  params: (schema: ZodTypeAny) => runValidation("params", schema),
  query: (schema: ZodTypeAny) => runValidation("query", schema),
};
