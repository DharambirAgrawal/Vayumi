import { and, desc, eq, gte, isNull, lt, lte, sql } from "drizzle-orm";
import { db } from "../../core/db/index.js";
import { meetings, type Meeting } from "../../core/db/schema/meetings.js";
import { NotFoundError } from "../../core/errors/index.js";
import { toMeetingDto } from "./meetings.types.js";
import type {
  ListMeetingsQuery,
  UpdateMeetingInput,
  UpsertMeetingInput,
} from "./meetings.validators.js";

const buildListConditions = (userId: string, query: ListMeetingsQuery) => {
  const conditions = [eq(meetings.userId, userId), isNull(meetings.deletedAt)];

  if (query.status) {
    conditions.push(eq(meetings.status, query.status));
  }
  if (query.from) {
    conditions.push(gte(meetings.startedAt, new Date(query.from)));
  }
  if (query.to) {
    conditions.push(lte(meetings.startedAt, new Date(query.to)));
  }
  if (query.cursor) {
    conditions.push(lt(meetings.startedAt, new Date(query.cursor)));
  }
  if (query.q) {
    conditions.push(
      sql`"meetings"."search_vector" @@ plainto_tsquery('english', ${query.q})`,
    );
  }

  return conditions;
};

const findOwned = async (userId: string, meetingId: string): Promise<Meeting | undefined> => {
  const [meeting] = await db
    .select()
    .from(meetings)
    .where(and(eq(meetings.id, meetingId), eq(meetings.userId, userId), isNull(meetings.deletedAt)))
    .limit(1);
  return meeting;
};

export const meetingsService = {
  /** Create or update a processed meeting (idempotent on (user_id, client_meeting_id)). */
  async upsertMeeting(userId: string, input: UpsertMeetingInput) {
    const now = new Date();
    const content = {
      title: input.title,
      status: input.status,
      startedAt: new Date(input.started_at),
      endedAt: input.ended_at ? new Date(input.ended_at) : null,
      durationMs: input.duration_ms,
      summary: input.summary ?? null,
      keyPoints: input.key_points,
      actionItems: input.action_items,
      transcript: input.transcript,
      suggestedReminders: input.suggested_reminders,
      analysisError: input.analysis_error ?? null,
      recordedOnDevice: input.recorded_on_device ?? null,
      recordedSessionId: input.recorded_session_id ?? null,
      updatedAt: now,
    };

    const [meeting] = await db
      .insert(meetings)
      .values({ userId, clientMeetingId: input.client_meeting_id, ...content })
      .onConflictDoUpdate({
        target: [meetings.userId, meetings.clientMeetingId],
        // Leave deleted_at untouched so a remote delete wins over a late re-upload.
        set: content,
      })
      .returning();

    return { meeting: toMeetingDto(meeting!) };
  },

  async listMeetings(userId: string, query: ListMeetingsQuery) {
    const rows = await db
      .select()
      .from(meetings)
      .where(and(...buildListConditions(userId, query)))
      .orderBy(desc(meetings.startedAt))
      .limit(query.limit);

    const last = rows[rows.length - 1];
    return {
      meetings: rows.map(toMeetingDto),
      next_cursor: rows.length === query.limit && last ? last.startedAt.toISOString() : null,
    };
  },

  async getMeeting(userId: string, meetingId: string) {
    const meeting = await findOwned(userId, meetingId);
    if (!meeting) {
      throw new NotFoundError("Meeting not found");
    }
    return { meeting: toMeetingDto(meeting) };
  },

  async updateMeeting(userId: string, meetingId: string, input: UpdateMeetingInput) {
    const existing = await findOwned(userId, meetingId);
    if (!existing) {
      throw new NotFoundError("Meeting not found");
    }

    const [updated] = await db
      .update(meetings)
      .set({
        title: input.title ?? existing.title,
        summary: input.summary !== undefined ? input.summary : existing.summary,
        keyPoints: input.key_points ?? existing.keyPoints,
        actionItems: input.action_items ?? existing.actionItems,
        suggestedReminders: input.suggested_reminders ?? existing.suggestedReminders,
        updatedAt: new Date(),
      })
      .where(eq(meetings.id, meetingId))
      .returning();

    return { meeting: toMeetingDto(updated!) };
  },

  /** Soft delete so other devices reconcile (and wipe their local audio) on next sync. */
  async deleteMeeting(userId: string, meetingId: string) {
    const deleted = await db
      .update(meetings)
      .set({ deletedAt: new Date(), updatedAt: new Date() })
      .where(and(eq(meetings.id, meetingId), eq(meetings.userId, userId), isNull(meetings.deletedAt)))
      .returning({ id: meetings.id });

    if (deleted.length === 0) {
      throw new NotFoundError("Meeting not found");
    }

    return { success: true };
  },
};
