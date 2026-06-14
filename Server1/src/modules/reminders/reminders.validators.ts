import { z } from "zod";
import { reminderRecurrences } from "../../core/db/schema/reminders.js";

const timezoneSchema = z.string().min(1).max(60);
const isoDateSchema = z.string().datetime({ offset: true });

export const createReminderSchema = z
  .object({
    user_id: z.string().uuid().optional(),
    title: z.string().min(1).max(255),
    body: z.string().max(5000).optional(),
    remind_at: isoDateSchema,
    timezone: timezoneSchema,
    recurrence: z.enum(reminderRecurrences).nullable().optional(),
    rrule: z.string().max(2000).nullable().optional(),
    max_fire_count: z.number().int().positive().nullable().optional(),
    source_meeting_id: z.string().uuid().nullable().optional(),
  })
  .superRefine((value, ctx) => {
    if (value.recurrence === "custom" && !value.rrule) {
      ctx.addIssue({
        code: z.ZodIssueCode.custom,
        path: ["rrule"],
        message: "rrule is required when recurrence is custom",
      });
    }
  });

export const updateReminderSchema = z
  .object({
    title: z.string().min(1).max(255).optional(),
    body: z.string().max(5000).nullable().optional(),
    remind_at: isoDateSchema.optional(),
    timezone: timezoneSchema.optional(),
    recurrence: z.enum(reminderRecurrences).nullable().optional(),
    rrule: z.string().max(2000).nullable().optional(),
    max_fire_count: z.number().int().positive().nullable().optional(),
    status: z.enum(["pending", "cancelled"]).optional(),
    source_meeting_id: z.string().uuid().nullable().optional(),
  })
  .refine((value) => Object.keys(value).length > 0, {
    message: "Provide at least one field to update",
  });

export const listRemindersQuerySchema = z.object({
  status: z.enum(["pending", "fired", "snoozed", "cancelled"]).optional(),
  source: z.enum(["user", "agent"]).optional(),
  from: isoDateSchema.optional(),
  to: isoDateSchema.optional(),
  limit: z.coerce.number().int().positive().max(100).default(20),
  cursor: z.string().uuid().optional(),
});

export const upcomingRemindersQuerySchema = z.object({
  days: z.coerce.number().int().positive().max(14).default(2),
});

export const snoozeReminderSchema = z.object({
  minutes: z.number().int().positive().max(24 * 60),
});

export type CreateReminderInput = z.infer<typeof createReminderSchema>;
export type UpdateReminderInput = z.infer<typeof updateReminderSchema>;
export type ListRemindersQuery = z.infer<typeof listRemindersQuerySchema>;
export type UpcomingRemindersQuery = z.infer<typeof upcomingRemindersQuerySchema>;
export type SnoozeReminderInput = z.infer<typeof snoozeReminderSchema>;
