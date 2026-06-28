import { z } from "zod";
import { appConfig } from "../../core/config/app.js";
import { meetingStatuses } from "../../core/db/schema/meetings.js";

const isoDate = z.string().datetime({ offset: true });
const { meeting: meetingLimits } = appConfig.limits;

const listEntry = z.string().max(meetingLimits.listItemMax);
const summaryField = z.string().max(meetingLimits.summaryMax);
const keyPointsField = z.array(listEntry).max(meetingLimits.listCountMax);
const actionItemsField = z.array(listEntry).max(meetingLimits.listCountMax);

// Transcript / suggested reminders are device-shaped blobs stored as-is; validate the
// fields we rely on (with size caps) and pass the rest through untouched.
const transcriptLineSchema = z
  .object({
    id: z.string().optional(),
    atMs: z.number().int().nonnegative().optional(),
    text: z.string().max(meetingLimits.transcriptSegmentTextMax),
    speaker: z.string().optional(),
  })
  .passthrough();

const suggestedReminderSchema = z
  .object({
    title: z.string().max(meetingLimits.titleMax),
    dueLabel: z.string().nullable().optional(),
    confirmed: z.boolean().optional(),
    reminderId: z.string().uuid().nullable().optional(),
  })
  .passthrough();

const suggestedRemindersField = z.array(suggestedReminderSchema).max(meetingLimits.listCountMax);

export const upsertMeetingSchema = z.object({
  client_meeting_id: z.string().min(1).max(120),
  title: z.string().min(1).max(meetingLimits.titleMax),
  status: z.enum(meetingStatuses).default("ready"),
  started_at: isoDate,
  ended_at: isoDate.nullable().optional(),
  duration_ms: z.number().int().nonnegative().default(0),
  summary: summaryField.nullable().optional(),
  key_points: keyPointsField.default([]),
  action_items: actionItemsField.default([]),
  transcript: z.array(transcriptLineSchema).max(meetingLimits.transcriptSegmentsMax).default([]),
  suggested_reminders: suggestedRemindersField.default([]),
  analysis_error: z.string().max(meetingLimits.summaryMax).nullable().optional(),
  recorded_on_device: z.string().max(120).nullable().optional(),
  recorded_session_id: z.string().uuid().nullable().optional(),
});

export const updateMeetingSchema = z
  .object({
    title: z.string().min(1).max(meetingLimits.titleMax).optional(),
    summary: summaryField.nullable().optional(),
    key_points: keyPointsField.optional(),
    action_items: actionItemsField.optional(),
    suggested_reminders: suggestedRemindersField.optional(),
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
