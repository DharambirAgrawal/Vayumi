import { z } from "zod";
import { appConfig } from "../../core/config/app.js";
import { memoryCategories, memorySources } from "../../core/db/schema/memory.js";

const isoDate = z.string().datetime({ offset: true });
const { memory: memoryLimits } = appConfig.limits;

export const upsertMemoryFactSchema = z.object({
  key: z.string().min(1).max(memoryLimits.keyMax),
  value: z.string().min(1).max(memoryLimits.valueMax),
  category: z.enum(memoryCategories).default("misc"),
  source: z.enum(memorySources).default("ai"),
  pinned: z.boolean().default(false),
  client_updated_at: isoDate.nullable().optional(),
});

export const syncPullQuerySchema = z.object({
  since: isoDate.optional(),
});

export const syncPushSchema = z
  .object({
    facts: z.array(upsertMemoryFactSchema).max(memoryLimits.syncFactsMax).default([]),
    deleted_keys: z.array(z.string().min(1).max(memoryLimits.keyMax)).max(memoryLimits.syncFactsMax).default([]),
  })
  .refine((v) => v.facts.length + v.deleted_keys.length > 0, {
    message: "Provide at least one change to sync.",
  });

export type UpsertMemoryFactInput = z.infer<typeof upsertMemoryFactSchema>;
export type SyncPullQuery = z.infer<typeof syncPullQuerySchema>;
export type SyncPushInput = z.infer<typeof syncPushSchema>;
