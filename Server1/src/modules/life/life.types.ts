import type {
  LifeEntryRow,
  LifeSource,
  LifeTabRow,
  LifeTabStatus,
} from "../../core/db/schema/life.js";

export type LifeTabDto = {
  id: string;
  client_tab_id: string;
  display_name: string;
  tab_type: string;
  layout: string;
  secondary_layout: string | null;
  icon: string;
  color: string;
  purpose: string | null;
  schema: unknown;
  settings: Record<string, unknown>;
  position: number;
  status: LifeTabStatus;
  source: LifeSource;
  client_created_at: string | null;
  client_updated_at: string | null;
  created_at: string;
  updated_at: string;
  deleted_at: string | null;
};

export type LifeEntryDto = {
  id: string;
  client_entry_id: string;
  client_tab_id: string;
  data: Record<string, unknown>;
  occurred_at: string;
  source: LifeSource;
  raw_input: string | null;
  reminder_id: string | null;
  client_created_at: string | null;
  client_updated_at: string | null;
  created_at: string;
  updated_at: string;
  deleted_at: string | null;
};

export const toLifeTabDto = (tab: LifeTabRow): LifeTabDto => ({
  id: tab.id,
  client_tab_id: tab.clientTabId,
  display_name: tab.displayName,
  tab_type: tab.tabType,
  layout: tab.layout,
  secondary_layout: tab.secondaryLayout,
  icon: tab.icon,
  color: tab.color,
  purpose: tab.purpose,
  schema: tab.schema,
  settings: (tab.settings as Record<string, unknown>) ?? {},
  position: tab.position,
  status: tab.status as LifeTabStatus,
  source: tab.source as LifeSource,
  client_created_at: tab.clientCreatedAt?.toISOString() ?? null,
  client_updated_at: tab.clientUpdatedAt?.toISOString() ?? null,
  created_at: tab.createdAt.toISOString(),
  updated_at: tab.updatedAt.toISOString(),
  deleted_at: tab.deletedAt?.toISOString() ?? null,
});

export const toLifeEntryDto = (entry: LifeEntryRow): LifeEntryDto => ({
  id: entry.id,
  client_entry_id: entry.clientEntryId,
  client_tab_id: entry.clientTabId,
  data: (entry.data as Record<string, unknown>) ?? {},
  occurred_at: entry.occurredAt.toISOString(),
  source: entry.source as LifeSource,
  raw_input: entry.rawInput,
  reminder_id: entry.reminderId,
  client_created_at: entry.clientCreatedAt?.toISOString() ?? null,
  client_updated_at: entry.clientUpdatedAt?.toISOString() ?? null,
  created_at: entry.createdAt.toISOString(),
  updated_at: entry.updatedAt.toISOString(),
  deleted_at: entry.deletedAt?.toISOString() ?? null,
});
