import { Router } from "express";
import { authenticate } from "../../../core/middleware/authenticate.js";

export const outlookRouter = Router();

outlookRouter.get("/connect", authenticate, (_req, res) => {
  res.status(501).json({ message: "Outlook connect is not implemented yet" });
});
