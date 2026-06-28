import type { MemoryCategory, MemoryFactRow, MemorySource } from "../../core/db/schema/memory.js";

export type MemoryFactDto = {
  id: string;
  key: string;
  value: string;
  category: MemoryCategory;
  source: MemorySource;
  pinned: boolean;
  client_updated_at: string | null;
  created_at: string;
  updated_at: string;
  deleted_at: string | null;
};

export const toMemoryFactDto = (fact: MemoryFactRow): MemoryFactDto => ({
  id: fact.id,
  key: fact.key,
  value: fact.value,
  category: fact.category as MemoryCategory,
  source: fact.source as MemorySource,
  pinned: fact.pinned,
  client_updated_at: fact.clientUpdatedAt?.toISOString() ?? null,
  created_at: fact.createdAt.toISOString(),
  updated_at: fact.updatedAt.toISOString(),
  deleted_at: fact.deletedAt?.toISOString() ?? null,
});
