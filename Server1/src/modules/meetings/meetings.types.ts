import type { Meeting, MeetingStatus } from "../../core/db/schema/meetings.js";

export type MeetingTranscriptLine = {
  id?: string;
  atMs?: number;
  text: string;
  speaker?: string;
  [key: string]: unknown;
};

export type MeetingSuggestedReminder = {
  title: string;
  dueLabel?: string | null;
  confirmed?: boolean;
  reminderId?: string | null;
  [key: string]: unknown;
};

export type MeetingDto = {
  id: string;
  client_meeting_id: string;
  title: string;
  status: MeetingStatus;
  started_at: string;
  ended_at: string | null;
  duration_ms: number;
  summary: string | null;
  key_points: string[];
  action_items: string[];
  transcript: MeetingTranscriptLine[];
  suggested_reminders: MeetingSuggestedReminder[];
  analysis_error: string | null;
  recorded_on_device: string | null;
  recorded_session_id: string | null;
  created_at: string;
  updated_at: string;
};

export const toMeetingDto = (meeting: Meeting): MeetingDto => ({
  id: meeting.id,
  client_meeting_id: meeting.clientMeetingId,
  title: meeting.title,
  status: meeting.status as MeetingStatus,
  started_at: meeting.startedAt.toISOString(),
  ended_at: meeting.endedAt?.toISOString() ?? null,
  duration_ms: meeting.durationMs,
  summary: meeting.summary,
  key_points: (meeting.keyPoints as string[]) ?? [],
  action_items: (meeting.actionItems as string[]) ?? [],
  transcript: (meeting.transcript as MeetingTranscriptLine[]) ?? [],
  suggested_reminders: (meeting.suggestedReminders as MeetingSuggestedReminder[]) ?? [],
  analysis_error: meeting.analysisError,
  recorded_on_device: meeting.recordedOnDevice,
  recorded_session_id: meeting.recordedSessionId,
  created_at: meeting.createdAt.toISOString(),
  updated_at: meeting.updatedAt.toISOString(),
});
