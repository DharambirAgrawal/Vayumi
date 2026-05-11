export type UserProfile = {
  id: string;
  email: string;
  name: string | null;
  avatar_url: string | null;
  is_verified: boolean;
  created_at: Date;
  updated_at: Date;
};
