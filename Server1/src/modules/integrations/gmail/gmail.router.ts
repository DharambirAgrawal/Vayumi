import { Router } from "express";
import { authenticate } from "../../../core/middleware/authenticate.js";

export const gmailRouter = Router();

gmailRouter.get("/connect", authenticate, (_req, res) => {
  res.status(501).json({ message: "Gmail connect is not implemented yet" });
});
