import pino from "pino";
import { env } from "../config/index.js";

const options: pino.LoggerOptions = {
  level: env.NODE_ENV === "production" ? "info" : "debug",
  serializers: {
    err: pino.stdSerializers.err,
  },
};

if (env.NODE_ENV !== "production") {
  options.transport = {
    target: "pino-pretty",
    options: { colorize: true, singleLine: true },
  };
}

export const logger = pino(options);
