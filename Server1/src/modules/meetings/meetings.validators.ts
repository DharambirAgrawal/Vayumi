import { z } from "zod";
import { meetingStatuses } from "../../core/db/schema/meetings.js";

const isoDate = z.string().datetime({ offset: true });

// Transcript / suggested reminders are device-shaped blobs stored as-is; validate the
// fields we rely on and pass the rest through untouched.
const transcriptLineSchema = z
  .object({
    id: z.string().optional(),
    atMs: z.number().int().nonnegative().optional(),
    text: z.string(),
    speaker: z.string().optional(),
  })
  .passthrough();

const suggestedReminderSchema = z
  .object({
    title: z.string().max(255),
    dueLabel: z.string().nullable().optional(),
    confirmed: z.boolean().optional(),
    reminderId: z.string().uuid().nullable().optional(),
  })
  .passthrough();

export const upsertMeetingSchema = z.object({
  client_meeting_id: z.string().min(1).max(120),
  title: z.string().min(1).max(255),
  status: z.enum(meetingStatuses).default("ready"),
  started_at: isoDate,
  ended_at: isoDate.nullable().optional(),
  duration_ms: z.number().int().nonnegative().default(0),
  summary: z.string().nullable().optional(),
  key_points: z.array(z.string()).default([]),
  action_items: z.array(z.string()).default([]),
  transcript: z.array(transcriptLineSchema).default([]),
  suggested_reminders: z.array(suggestedReminderSchema).default([]),
  analysis_error: z.string().nullable().optional(),
  recorded_on_device: z.string().max(120).nullable().optional(),
  recorded_session_id: z.string().uuid().nullable().optional(),
});

export const updateMeetingSchema = z
  .object({
    title: z.string().min(1).max(255).optional(),
    summary: z.string().nullable().optional(),
    key_points: z.array(z.string()).optional(),
    action_items: z.array(z.string()).optional(),
    suggested_reminders: z.array(suggestedReminderSchema).optional(),
  })
  .refine((value) => Object.keys(value).length > 0, {
    message: "Provide at least one field to update",
  });

export const listMeetingsQuerySchema = z.object({
  q: z.string().max(200).optional(),
  status: z.enum(meetingStatuses).optional(),
  from: isoDate.optional(),
  to: isoDate.optional(),
  limit: z.coerce.number().int().positive().max(100).default(20),
  cursor: isoDate.optional(),
});

export type UpsertMeetingInput = z.infer<typeof upsertMeetingSchema>;
export type UpdateMeetingInput = z.infer<typeof updateMeetingSchema>;
export type ListMeetingsQuery = z.infer<typeof listMeetingsQuerySchema>;
