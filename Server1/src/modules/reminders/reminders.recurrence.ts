import rrulePkg from "rrule";

const { RRule } = rrulePkg;
import type { ReminderRecurrence } from "../../core/db/schema/reminders.js";

const addDays = (date: Date, days: number): Date => {
  const next = new Date(date);
  next.setUTCDate(next.getUTCDate() + days);
  return next;
};

const addMonths = (date: Date, months: number): Date => {
  const next = new Date(date);
  next.setUTCMonth(next.getUTCMonth() + months);
  return next;
};

export const computeInitialNextFireAt = (input: {
  remindAt: Date;
  recurrence: ReminderRecurrence | null;
  rrule: string | null;
}): Date => {
  const now = new Date();
  if (!input.recurrence && !input.rrule) {
    return input.remindAt;
  }

  return computeNextFireAt({
    after: now,
    recurrence: input.recurrence,
    rrule: input.rrule,
    fallback: input.remindAt,
  });
};

export const computeNextFireAt = (input: {
  after: Date;
  recurrence: ReminderRecurrence | null;
  rrule: string | null;
  fallback: Date;
}): Date => {
  if (input.rrule) {
    try {
      const rule = RRule.fromString(input.rrule);
      const next = rule.after(input.after, false);
      if (next) {
        return next;
      }
    } catch {
      return input.fallback;
    }
  }

  switch (input.recurrence) {
    case "daily":
      return addDays(input.after, 1);
    case "weekly":
      return addDays(input.after, 7);
    case "monthly":
      return addMonths(input.after, 1);
    default:
      return input.fallback;
  }
};

export const hasRecurrence = (recurrence: ReminderRecurrence | null, rrule: string | null): boolean =>
  Boolean(recurrence || rrule);
