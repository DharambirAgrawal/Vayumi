/**
 * Type definitions for Vayumi client
 */

export type ConnectionState =
  | 'disconnected'
  | 'connecting'
  | 'connected_idle'
  | 'wake_detected'
  | 'streaming_audio'
  | 'waiting_response'
  | 'ai_speaking'
  | 'interrupting';

export type Mode = 'conversation' | 'meeting';
export type ClientType = 'web' | 'hardware';
export type ContentType = 'text' | 'image' | 'link' | 'voice';
export type RespondVia = 'voice_and_chat' | 'chat_only' | 'voice_only';

export interface AudioConfig {
  sample_rate: number;
  channels: number;
  bit_depth: number;
}

export interface ChatMessage {
  text?: string;
  attachments?: Attachment[];
  respond_via?: RespondVia;
  interrupt_policy?: 'queue' | 'replace';
}

export interface Attachment {
  type: ContentType;
  data?: string;
  url?: string;
  mime_type?: string;
}

export interface ChatResponse {
  text: string;
  spoken: boolean;
  response_id: string;
}

export interface AuthUser {
  id: string;
  email: string;
  name?: string | null;
}

export interface AuthResponse {
  user: AuthUser;
  access_token: string;
  token_type: 'bearer';
}

export interface DiarizationSegment {
  speaker: string;
  text: string;
  start_ms: number;
  end_ms: number;
}

export interface InterruptAck {
  flushed_response_id?: string;
  queued_chars_dropped: number;
}

export interface VayumiError {
  code: string;
  message: string;
  fatal: boolean;
}

export type EventCallback<T> = (data: T) => void;
export type StateChangeCallback = (state: ConnectionState) => void;
