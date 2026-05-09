export type SessionView = {
  id: string;
  device_type: string;
  device_name: string | null;
  device_fingerprint: string | null;
  last_seen_at: Date;
  created_at: Date;
  expires_at: Date;
  is_current: boolean;
};
