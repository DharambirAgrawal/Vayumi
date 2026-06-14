import cors from "cors";
import express from "express";
import helmet from "helmet";
import { appConfig } from "./core/config/app.js";
import { errorHandler } from "./core/middleware/errorHandler.js";
import { rateLimiter } from "./core/middleware/rateLimiter.js";
import { requestLogger } from "./core/middleware/requestLogger.js";
import { apiRouter, internalRouter } from "./routes/index.js";

export const app = express();

app.set("trust proxy", 1);
app.use(requestLogger);
app.use(
  cors({
    origin: (origin, callback) => {
      if (!origin || appConfig.cors.origins.includes(origin)) {
        callback(null, true);
        return;
      }
      callback(new Error("Not allowed by CORS"));
    },
    credentials: true,
  }),
);
app.use(helmet());
// 5 MB to accommodate long meeting transcripts (bounded on-device by a recording duration cap).
app.use(express.json({ limit: "5mb" }));
app.use(rateLimiter({ ...appConfig.rateLimit.global, keyPrefix: "global" }));
app.use("/api/v1", apiRouter);
app.use("/internal", internalRouter);
app.use(errorHandler);
