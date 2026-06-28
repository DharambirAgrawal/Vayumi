import { z } from "zod";
import { appConfig } from "../../core/config/app.js";
import { lifeLayouts, lifeSources, lifeTabStatuses } from "../../core/db/schema/life.js";

const isoDate = z.string().datetime({ offset: true });
const { life: lifeLimits } = appConfig.limits;

// Query booleans arrive as strings — only "true"/"1" mean true (z.coerce.boolean
// would turn the string "false" into true, since any non-empty string is truthy).
const booleanQuery = z
  .union([z.boolean(), z.string()])
  .optional()
  .transform((v) => v === true || v === "true" || v === "1");

const bytesAtMost = (max: number, label: string) =>
  z.unknown().superRefine((value, ctx) => {
    if (value === undefined || value === null) return;
    const size = Buffer.byteLength(JSON.stringify(value), "utf8");
    if (size > max) {
      ctx.addIssue({
        code: z.ZodIssueCode.custom,
        message: `${label} exceeds ${max} bytes (${size}).`,
      });
    }
  });

// A tab's field schema is device-shaped; cap its size and pass the structure
// through untouched (the device validates entry data against it, not the server).
const tabSchemaField = bytesAtMost(lifeLimits.schemaBytesMax, "schema");
const entryDataField = z
  .record(z.string(), z.unknown())
  .and(bytesAtMost(lifeLimits.entryDataBytesMax, "data"));

export const upsertLifeTabSchema = z.object({
  client_tab_id: z.string().min(1).max(120),
  display_name: z.string().min(1).max(lifeLimits.tabNameMax),
  tab_type: z.string().min(1).max(60),
  layout: z.enum(lifeLayouts).default("timeline"),
  secondary_layout: z.enum(lifeLayouts).nullable().optional(),
  icon: z.string().max(60).default("sparkles-outline"),
  color: z.string().max(20).default("#EE6A5E"),
  purpose: z.string().max(lifeLimits.purposeMax).nullable().optional(),
  schema: tabSchemaField,
  settings: z.record(z.string(), z.unknown()).default({}),
  position: z.number().int().nonnegative().default(0),
  status: z.enum(lifeTabStatuses).default("active"),
  source: z.enum(lifeSources).default("user"),
  client_created_at: isoDate.nullable().optional(),
  client_updated_at: isoDate.nullable().optional(),
});

export const upsertLifeEntrySchema = z.object({
  client_entry_id: z.string().min(1).max(120),
  client_tab_id: z.string().min(1).max(120),
  data: entryDataField,
  occurred_at: isoDate,
  source: z.enum(lifeSources).default("user"),
  raw_input: z.string().max(lifeLimits.rawInputMax).nullable().optional(),
  reminder_id: z.string().max(120).nullable().optional(),
  client_created_at: isoDate.nullable().optional(),
  client_updated_at: isoDate.nullable().optional(),
});

export const listLifeTabsQuerySchema = z.object({
  status: z.enum(lifeTabStatuses).optional(),
  include_deleted: booleanQuery,
  since: isoDate.optional(),
});

export const listLifeEntriesQuerySchema = z.object({
  tab_id: z.string().max(120).optional(),
  from: isoDate.optional(),
  to: isoDate.optional(),
  include_deleted: booleanQuery,
  since: isoDate.optional(),
  limit: z.coerce.number().int().positive().max(500).default(100),
  cursor: isoDate.optional(),
});

// Pull everything changed since a watermark (for multi-device reconcile).
export const syncPullQuerySchema = z.object({
  since: isoDate.optional(),
});

// Push a batch of local changes in one round-trip.
export const syncPushSchema = z
  .object({
    tabs: z.array(upsertLifeTabSchema).max(lifeLimits.syncTabsMax).default([]),
    entries: z.array(upsertLifeEntrySchema).max(lifeLimits.syncEntriesMax).default([]),
    deleted_tab_ids: z.array(z.string().min(1).max(120)).max(lifeLimits.syncTabsMax).default([]),
    deleted_entry_ids: z
      .array(z.string().min(1).max(120))
      .max(lifeLimits.syncEntriesMax)
      .default([]),
  })
  .refine(
    (v) =>
      v.tabs.length + v.entries.length + v.deleted_tab_ids.length + v.deleted_entry_ids.length > 0,
    { message: "Provide at least one change to sync." },
  );

export type UpsertLifeTabInput = z.infer<typeof upsertLifeTabSchema>;
export type UpsertLifeEntryInput = z.infer<typeof upsertLifeEntrySchema>;
export type ListLifeTabsQuery = z.infer<typeof listLifeTabsQuerySchema>;
export type ListLifeEntriesQuery = z.infer<typeof listLifeEntriesQuerySchema>;
export type SyncPullQuery = z.infer<typeof syncPullQuerySchema>;
export type SyncPushInput = z.infer<typeof syncPushSchema>;
