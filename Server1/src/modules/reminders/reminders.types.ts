import type { Reminder, ReminderRecurrence, ReminderSource, ReminderStatus } from "../../core/db/schema/reminders.js";

export type ReminderDto = {
  id: string;
  user_id: string;
  title: string;
  body: string | null;
  remind_at: string;
  timezone: string;
  recurrence: ReminderRecurrence | null;
  rrule: string | null;
  next_fire_at: string;
  status: ReminderStatus;
  source: ReminderSource;
  snooze_until: string | null;
  fired_at: string | null;
  fire_count: number;
  max_fire_count: number | null;
  agent_delivered: boolean;
  push_delivered: boolean;
  source_meeting_id: string | null;
  created_at: string;
  updated_at: string;
};

export const toReminderDto = (reminder: Reminder): ReminderDto => ({
  id: reminder.id,
  user_id: reminder.userId,
  title: reminder.title,
  body: reminder.body,
  remind_at: reminder.remindAt.toISOString(),
  timezone: reminder.timezone,
  recurrence: reminder.recurrence as ReminderRecurrence | null,
  rrule: reminder.rrule,
  next_fire_at: reminder.nextFireAt.toISOString(),
  status: reminder.status as ReminderStatus,
  source: reminder.source as ReminderSource,
  snooze_until: reminder.snoozeUntil?.toISOString() ?? null,
  fired_at: reminder.firedAt?.toISOString() ?? null,
  fire_count: reminder.fireCount,
  max_fire_count: reminder.maxFireCount,
  agent_delivered: reminder.agentDelivered,
  push_delivered: reminder.pushDelivered,
  source_meeting_id: reminder.sourceMeetingId,
  created_at: reminder.createdAt.toISOString(),
  updated_at: reminder.updatedAt.toISOString(),
});

export type AgentEventType =
  | "reminder.fired"
  | "reminder.snoozed"
  | "reminder.cancelled"
  | "email.received";
