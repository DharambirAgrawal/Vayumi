import { and, asc, eq, gt, inArray, lte } from "drizzle-orm";
import { remindersConfig } from "../../core/config/reminders.js";
import { db } from "../../core/db/index.js";
import { reminders, type Reminder, type ReminderRecurrence } from "../../core/db/schema/reminders.js";
import { NotFoundError, ValidationError } from "../../core/errors/index.js";
import { redis } from "../../core/redis/index.js";
import { RedisKeys, RedisTTL } from "../../core/redis/keys.js";
import { logger } from "../../core/utils/logger.js";
import { notificationsService } from "../notifications/notifications.service.js";
import {
  computeInitialNextFireAt,
  computeNextFireAt,
  hasRecurrence,
} from "./reminders.recurrence.js";
import { server2AgentClient } from "./server2.agentClient.js";
import { toReminderDto } from "./reminders.types.js";
import type {
  CreateReminderInput,
  ListRemindersQuery,
  SnoozeReminderInput,
  UpcomingRemindersQuery,
  UpdateReminderInput,
} from "./reminders.validators.js";

const resolveRecurrence = (
  recurrence: ReminderRecurrence | null | undefined,
  rrule: string | null | undefined,
): { recurrence: ReminderRecurrence | null; rrule: string | null } => ({
  recurrence: recurrence ?? null,
  rrule: rrule ?? null,
});

const buildListConditions = (userId: string, query: ListRemindersQuery) => {
  const conditions = [eq(reminders.userId, userId)];

  if (query.status) {
    conditions.push(eq(reminders.status, query.status));
  }
  if (query.source) {
    conditions.push(eq(reminders.source, query.source));
  }
  if (query.from) {
    conditions.push(gt(reminders.nextFireAt, new Date(query.from)));
  }
  if (query.to) {
    conditions.push(lte(reminders.nextFireAt, new Date(query.to)));
  }
  if (query.cursor) {
    conditions.push(gt(reminders.id, query.cursor));
  }

  return conditions;
};

const dispatchPushToUser = async (userId: string, title: string, body: string, reminderId: string) =>
  notificationsService.sendPushToUser(userId, {
    title,
    body,
    data: {
      type: "reminder.fired",
      reminder_id: reminderId,
    },
  });

const scheduleAfterFire = (reminder: Reminder, firedAt: Date) => {
  const recurring = hasRecurrence(
    reminder.recurrence as ReminderRecurrence | null,
    reminder.rrule,
  );
  const nextCount = reminder.fireCount + 1;

  if (!recurring) {
    return {
      status: "fired" as const,
      nextFireAt: reminder.nextFireAt,
      snoozeUntil: null as Date | null,
    };
  }

  if (reminder.maxFireCount !== null && nextCount >= reminder.maxFireCount) {
    return {
      status: "cancelled" as const,
      nextFireAt: reminder.nextFireAt,
      snoozeUntil: null as Date | null,
    };
  }

  const nextFireAt = computeNextFireAt({
    after: firedAt,
    recurrence: reminder.recurrence as ReminderRecurrence | null,
    rrule: reminder.rrule,
    fallback: firedAt,
  });

  return {
    status: "pending" as const,
    nextFireAt,
    snoozeUntil: null as Date | null,
  };
};

const processDueReminder = async (reminder: Reminder) => {
  const firedAt = new Date();
  const schedule = scheduleAfterFire(reminder, firedAt);
  const bodyText = reminder.body ?? reminder.title;

  const pushDelivered = await dispatchPushToUser(reminder.userId, reminder.title, bodyText, reminder.id);

  const agentDelivered = await server2AgentClient.sendAgentEvent({
    type: "reminder.fired",
    userId: reminder.userId,
    payload: {
      reminderId: reminder.id,
      title: reminder.title,
      body: reminder.body,
      firedAt: firedAt.toISOString(),
      source: reminder.source,
    },
  });

  const [updated] = await db
    .update(reminders)
    .set({
      status: schedule.status,
      firedAt,
      fireCount: reminder.fireCount + 1,
      nextFireAt: schedule.nextFireAt,
      snoozeUntil: schedule.snoozeUntil,
      pushDelivered,
      agentDelivered,
      updatedAt: new Date(),
    })
    .where(eq(reminders.id, reminder.id))
    .returning();

  return updated;
};

export const remindersService = {
  async createReminder(userId: string, input: CreateReminderInput, source: "user" | "agent") {
    const remindAt = new Date(input.remind_at);
    const { recurrence, rrule } = resolveRecurrence(input.recurrence, input.rrule);
    const nextFireAt = computeInitialNextFireAt({ remindAt, recurrence, rrule });

    const [reminder] = await db
      .insert(reminders)
      .values({
        userId,
        title: input.title,
        body: input.body ?? null,
        remindAt,
        timezone: input.timezone,
        recurrence,
        rrule,
        nextFireAt,
        status: "pending",
        source,
        maxFireCount: input.max_fire_count ?? null,
        sourceMeetingId: input.source_meeting_id ?? null,
      })
      .returning();

    return { reminder: toReminderDto(reminder!) };
  },

  async listReminders(userId: string, query: ListRemindersQuery) {
    const rows = await db
      .select()
      .from(reminders)
      .where(and(...buildListConditions(userId, query)))
      .orderBy(asc(reminders.nextFireAt), asc(reminders.id))
      .limit(query.limit);

    return {
      reminders: rows.map(toReminderDto),
      next_cursor: rows.length === query.limit ? rows[rows.length - 1]?.id ?? null : null,
    };
  },

  async listUpcoming(userId: string, query: UpcomingRemindersQuery) {
    const now = new Date();
    const cutoff = new Date(now);
    cutoff.setUTCDate(cutoff.getUTCDate() + query.days);

    const rows = await db
      .select()
      .from(reminders)
      .where(
        and(
          eq(reminders.userId, userId),
          eq(reminders.status, "pending"),
          gt(reminders.nextFireAt, now),
          lte(reminders.nextFireAt, cutoff),
        ),
      )
      .orderBy(asc(reminders.nextFireAt));

    return { reminders: rows.map(toReminderDto) };
  },

  async getReminder(userId: string, reminderId: string) {
    const [reminder] = await db
      .select()
      .from(reminders)
      .where(and(eq(reminders.id, reminderId), eq(reminders.userId, userId)))
      .limit(1);

    if (!reminder) {
      throw new NotFoundError("Reminder not found");
    }

    return { reminder: toReminderDto(reminder) };
  },

  async updateReminder(userId: string, reminderId: string, input: UpdateReminderInput) {
    const [existing] = await db
      .select()
      .from(reminders)
      .where(and(eq(reminders.id, reminderId), eq(reminders.userId, userId)))
      .limit(1);

    if (!existing) {
      throw new NotFoundError("Reminder not found");
    }

    const remindAt = input.remind_at ? new Date(input.remind_at) : existing.remindAt;
    const timezone = input.timezone ?? existing.timezone;
    const recurrence =
      input.recurrence !== undefined
        ? input.recurrence
        : (existing.recurrence as ReminderRecurrence | null);
    const rrule = input.rrule !== undefined ? input.rrule : existing.rrule;

    const nextFireAt =
      input.remind_at || input.recurrence !== undefined || input.rrule !== undefined
        ? computeInitialNextFireAt({
            remindAt,
            recurrence,
            rrule,
          })
        : existing.nextFireAt;

    const [updated] = await db
      .update(reminders)
      .set({
        title: input.title ?? existing.title,
        body: input.body !== undefined ? input.body : existing.body,
        remindAt,
        timezone,
        recurrence,
        rrule,
        nextFireAt,
        maxFireCount:
          input.max_fire_count !== undefined ? input.max_fire_count : existing.maxFireCount,
        status: input.status ?? existing.status,
        sourceMeetingId:
          input.source_meeting_id !== undefined
            ? input.source_meeting_id
            : existing.sourceMeetingId,
        updatedAt: new Date(),
      })
      .where(eq(reminders.id, reminderId))
      .returning();

    return { reminder: toReminderDto(updated!) };
  },

  async deleteReminder(userId: string, reminderId: string) {
    const deleted = await db
      .delete(reminders)
      .where(and(eq(reminders.id, reminderId), eq(reminders.userId, userId)))
      .returning({ id: reminders.id });

    if (deleted.length === 0) {
      throw new NotFoundError("Reminder not found");
    }

    return { success: true };
  },

  async snoozeReminder(userId: string, reminderId: string, input: SnoozeReminderInput) {
    const [existing] = await db
      .select()
      .from(reminders)
      .where(and(eq(reminders.id, reminderId), eq(reminders.userId, userId)))
      .limit(1);

    if (!existing) {
      throw new NotFoundError("Reminder not found");
    }

    if (!["pending", "snoozed"].includes(existing.status)) {
      throw new ValidationError("Only pending reminders can be snoozed");
    }

    const snoozeUntil = new Date(Date.now() + input.minutes * 60 * 1000);

    const [updated] = await db
      .update(reminders)
      .set({
        status: "snoozed",
        snoozeUntil,
        nextFireAt: snoozeUntil,
        updatedAt: new Date(),
      })
      .where(eq(reminders.id, reminderId))
      .returning();

    return { reminder: toReminderDto(updated!) };
  },

  async cancelReminder(userId: string, reminderId: string) {
    const [existing] = await db
      .select()
      .from(reminders)
      .where(and(eq(reminders.id, reminderId), eq(reminders.userId, userId)))
      .limit(1);

    if (!existing) {
      throw new NotFoundError("Reminder not found");
    }

    const [updated] = await db
      .update(reminders)
      .set({
        status: "cancelled",
        updatedAt: new Date(),
      })
      .where(eq(reminders.id, reminderId))
      .returning();

    void server2AgentClient.sendAgentEvent({
      type: "reminder.cancelled",
      userId,
      payload: {
        reminderId,
        title: existing.title,
        source: existing.source,
      },
    });

    return { reminder: toReminderDto(updated!) };
  },

  async fireRemindersNow() {
    const acquired = await redis.setIfNotExists(
      RedisKeys.reminderFireLock(),
      "1",
      RedisTTL.reminderFireLock,
    );

    if (!acquired) {
      return { processed: 0, skipped: true };
    }

    try {
      const now = new Date();
      const due = await db
        .select()
        .from(reminders)
        .where(
          and(
            lte(reminders.nextFireAt, now),
            inArray(reminders.status, ["pending", "snoozed"]),
          ),
        )
        .orderBy(asc(reminders.nextFireAt))
        .limit(remindersConfig.fireBatchSize);

      const results = await Promise.allSettled(due.map((reminder) => processDueReminder(reminder)));

      for (const result of results) {
        if (result.status === "rejected") {
          logger.error({ error: result.reason }, "Failed to fire reminder");
        }
      }

      return {
        processed: results.filter((result) => result.status === "fulfilled").length,
        skipped: false,
      };
    } finally {
      await redis.del(RedisKeys.reminderFireLock());
    }
  },
};
