import { and, desc, eq, gt, gte, inArray, isNull, lt, lte } from "drizzle-orm";
import { db } from "../../core/db/index.js";
import {
  lifeEntries,
  lifeTabs,
  type LifeEntryRow,
  type LifeTabRow,
} from "../../core/db/schema/life.js";
import { NotFoundError } from "../../core/errors/index.js";
import { toLifeEntryDto, toLifeTabDto } from "./life.types.js";
import type {
  ListLifeEntriesQuery,
  ListLifeTabsQuery,
  SyncPullQuery,
  SyncPushInput,
  UpsertLifeEntryInput,
  UpsertLifeTabInput,
} from "./life.validators.js";

const toDate = (value?: string | null): Date | null => (value ? new Date(value) : null);

const tabContent = (input: UpsertLifeTabInput, now: Date) => ({
  displayName: input.display_name,
  tabType: input.tab_type,
  layout: input.layout,
  secondaryLayout: input.secondary_layout ?? null,
  icon: input.icon,
  color: input.color,
  purpose: input.purpose ?? null,
  schema: input.schema,
  settings: input.settings,
  position: input.position,
  status: input.status,
  source: input.source,
  clientCreatedAt: toDate(input.client_created_at),
  clientUpdatedAt: toDate(input.client_updated_at),
  updatedAt: now,
  // A re-upload of a previously deleted tab resurrects it (device is the source of truth).
  deletedAt: null,
});

const entryContent = (input: UpsertLifeEntryInput, now: Date) => ({
  clientTabId: input.client_tab_id,
  data: input.data,
  occurredAt: new Date(input.occurred_at),
  source: input.source,
  rawInput: input.raw_input ?? null,
  reminderId: input.reminder_id ?? null,
  clientCreatedAt: toDate(input.client_created_at),
  clientUpdatedAt: toDate(input.client_updated_at),
  updatedAt: now,
  deletedAt: null,
});

const upsertTabRow = async (userId: string, input: UpsertLifeTabInput, now: Date) => {
  const content = tabContent(input, now);
  const [row] = await db
    .insert(lifeTabs)
    .values({ userId, clientTabId: input.client_tab_id, ...content })
    .onConflictDoUpdate({ target: [lifeTabs.userId, lifeTabs.clientTabId], set: content })
    .returning();
  return row!;
};

const upsertEntryRow = async (userId: string, input: UpsertLifeEntryInput, now: Date) => {
  const content = entryContent(input, now);
  const [row] = await db
    .insert(lifeEntries)
    .values({ userId, clientEntryId: input.client_entry_id, ...content })
    .onConflictDoUpdate({ target: [lifeEntries.userId, lifeEntries.clientEntryId], set: content })
    .returning();
  return row!;
};

const softDeleteTabs = async (userId: string, clientTabIds: string[], now: Date) => {
  if (clientTabIds.length === 0) return;
  await db
    .update(lifeTabs)
    .set({ deletedAt: now, updatedAt: now })
    .where(and(eq(lifeTabs.userId, userId), inArray(lifeTabs.clientTabId, clientTabIds)));
  // Cascade: a deleted tracker takes its entries with it so devices stay consistent.
  await db
    .update(lifeEntries)
    .set({ deletedAt: now, updatedAt: now })
    .where(and(eq(lifeEntries.userId, userId), inArray(lifeEntries.clientTabId, clientTabIds)));
};

const softDeleteEntries = async (userId: string, clientEntryIds: string[], now: Date) => {
  if (clientEntryIds.length === 0) return;
  await db
    .update(lifeEntries)
    .set({ deletedAt: now, updatedAt: now })
    .where(and(eq(lifeEntries.userId, userId), inArray(lifeEntries.clientEntryId, clientEntryIds)));
};

export const lifeService = {
  async upsertTab(userId: string, input: UpsertLifeTabInput) {
    const tab = await upsertTabRow(userId, input, new Date());
    return { tab: toLifeTabDto(tab) };
  },

  async upsertEntry(userId: string, input: UpsertLifeEntryInput) {
    const entry = await upsertEntryRow(userId, input, new Date());
    return { entry: toLifeEntryDto(entry) };
  },

  async listTabs(userId: string, query: ListLifeTabsQuery) {
    const conditions = [eq(lifeTabs.userId, userId)];
    if (!query.include_deleted && !query.since) conditions.push(isNull(lifeTabs.deletedAt));
    if (query.status) conditions.push(eq(lifeTabs.status, query.status));
    if (query.since) conditions.push(gt(lifeTabs.updatedAt, new Date(query.since)));

    const rows = await db
      .select()
      .from(lifeTabs)
      .where(and(...conditions))
      .orderBy(lifeTabs.position);
    return { tabs: rows.map(toLifeTabDto) };
  },

  async listEntries(userId: string, query: ListLifeEntriesQuery) {
    const conditions = [eq(lifeEntries.userId, userId)];
    if (!query.include_deleted && !query.since) conditions.push(isNull(lifeEntries.deletedAt));
    if (query.tab_id) conditions.push(eq(lifeEntries.clientTabId, query.tab_id));
    if (query.from) conditions.push(gte(lifeEntries.occurredAt, new Date(query.from)));
    if (query.to) conditions.push(lte(lifeEntries.occurredAt, new Date(query.to)));
    if (query.since) conditions.push(gt(lifeEntries.updatedAt, new Date(query.since)));
    if (query.cursor) conditions.push(lt(lifeEntries.occurredAt, new Date(query.cursor)));

    const rows = await db
      .select()
      .from(lifeEntries)
      .where(and(...conditions))
      .orderBy(desc(lifeEntries.occurredAt))
      .limit(query.limit);

    const last = rows[rows.length - 1];
    return {
      entries: rows.map(toLifeEntryDto),
      next_cursor: rows.length === query.limit && last ? last.occurredAt.toISOString() : null,
    };
  },

  async deleteTab(userId: string, clientTabId: string) {
    const existing = await db
      .select({ id: lifeTabs.id })
      .from(lifeTabs)
      .where(and(eq(lifeTabs.userId, userId), eq(lifeTabs.clientTabId, clientTabId), isNull(lifeTabs.deletedAt)))
      .limit(1);
    if (existing.length === 0) throw new NotFoundError("Tracker not found");
    await softDeleteTabs(userId, [clientTabId], new Date());
    return { success: true };
  },

  async deleteEntry(userId: string, clientEntryId: string) {
    const deleted = await db
      .update(lifeEntries)
      .set({ deletedAt: new Date(), updatedAt: new Date() })
      .where(
        and(
          eq(lifeEntries.userId, userId),
          eq(lifeEntries.clientEntryId, clientEntryId),
          isNull(lifeEntries.deletedAt),
        ),
      )
      .returning({ id: lifeEntries.id });
    if (deleted.length === 0) throw new NotFoundError("Entry not found");
    return { success: true };
  },

  /** Pull everything (or everything changed since a watermark) for device reconcile. */
  async syncPull(userId: string, query: SyncPullQuery) {
    const since = query.since ? new Date(query.since) : null;
    const tabWhere = since
      ? and(eq(lifeTabs.userId, userId), gt(lifeTabs.updatedAt, since))
      : and(eq(lifeTabs.userId, userId), isNull(lifeTabs.deletedAt));
    const entryWhere = since
      ? and(eq(lifeEntries.userId, userId), gt(lifeEntries.updatedAt, since))
      : and(eq(lifeEntries.userId, userId), isNull(lifeEntries.deletedAt));

    const [tabs, entries] = await Promise.all([
      db.select().from(lifeTabs).where(tabWhere).orderBy(lifeTabs.position),
      db.select().from(lifeEntries).where(entryWhere).orderBy(desc(lifeEntries.occurredAt)),
    ]);

    return {
      tabs: tabs.map(toLifeTabDto),
      entries: entries.map(toLifeEntryDto),
      // Watermark the device stores and sends back as `since` next time.
      server_time: new Date().toISOString(),
    };
  },

  /** Apply a batch of local changes (upserts + soft deletes) in one call. */
  async syncPush(userId: string, input: SyncPushInput) {
    const now = new Date();
    const tabs: LifeTabRow[] = [];
    const entries: LifeEntryRow[] = [];

    for (const tab of input.tabs) tabs.push(await upsertTabRow(userId, tab, now));
    for (const entry of input.entries) entries.push(await upsertEntryRow(userId, entry, now));
    await softDeleteTabs(userId, input.deleted_tab_ids, now);
    await softDeleteEntries(userId, input.deleted_entry_ids, now);

    return {
      tabs: tabs.map(toLifeTabDto),
      entries: entries.map(toLifeEntryDto),
      deleted_tabs: input.deleted_tab_ids.length,
      deleted_entries: input.deleted_entry_ids.length,
      server_time: now.toISOString(),
    };
  },
};
