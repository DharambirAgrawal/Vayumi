import { z } from "zod";
import { appConfig } from "../../core/config/app.js";

const { ai: aiLimits } = appConfig.limits;

// Messages / tools are OpenAI-shaped; we validate the envelope + caps and pass the
// structure through (the upstream provider is the source of truth on shape).
const messageSchema = z
  .object({
    role: z.enum(["system", "user", "assistant", "tool"]),
    content: z.union([z.string(), z.null()]).optional(),
  })
  .passthrough();

export const chatRequestSchema = z
  .object({
    messages: z.array(messageSchema).min(1).max(aiLimits.maxMessages),
    tools: z.array(z.record(z.string(), z.unknown())).max(aiLimits.maxTools).optional(),
    tool_choice: z.union([z.string(), z.record(z.string(), z.unknown())]).optional(),
    temperature: z.number().min(0).max(2).optional(),
    max_tokens: z.number().int().positive().max(aiLimits.maxOutputTokens).optional(),
    provider: z.enum(["groq", "cerebras", "gemini"]).optional(),
  })
  .superRefine((value, ctx) => {
    const size = Buffer.byteLength(JSON.stringify(value), "utf8");
    if (size > aiLimits.maxBodyChars) {
      ctx.addIssue({
        code: z.ZodIssueCode.custom,
        message: `Request too large (${size} > ${aiLimits.maxBodyChars} bytes).`,
      });
    }
  });

export type ChatRequestInput = z.infer<typeof chatRequestSchema>;
