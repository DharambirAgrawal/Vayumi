import { and, eq, gt, inArray, isNull } from "drizzle-orm";
import { db } from "../../core/db/index.js";
import { memoryFacts, type MemoryFactRow } from "../../core/db/schema/memory.js";
import { toMemoryFactDto } from "./memory.types.js";
import type { SyncPullQuery, SyncPushInput, UpsertMemoryFactInput } from "./memory.validators.js";

const toDate = (value?: string | null): Date | null => (value ? new Date(value) : null);

const factContent = (input: UpsertMemoryFactInput, now: Date) => ({
  value: input.value,
  category: input.category,
  source: input.source,
  pinned: input.pinned,
  clientUpdatedAt: toDate(input.client_updated_at),
  updatedAt: now,
  // A re-upload resurrects a previously forgotten fact (device is source of truth).
  deletedAt: null,
});

const upsertFactRow = async (userId: string, input: UpsertMemoryFactInput, now: Date) => {
  const content = factContent(input, now);
  const [row] = await db
    .insert(memoryFacts)
    .values({ userId, key: input.key, ...content })
    .onConflictDoUpdate({ target: [memoryFacts.userId, memoryFacts.key], set: content })
    .returning();
  return row!;
};

export const memoryService = {
  /** Pull all facts (or those changed since a watermark) for device reconcile. */
  async syncPull(userId: string, query: SyncPullQuery) {
    const since = query.since ? new Date(query.since) : null;
    const where = since
      ? and(eq(memoryFacts.userId, userId), gt(memoryFacts.updatedAt, since))
      : and(eq(memoryFacts.userId, userId), isNull(memoryFacts.deletedAt));
    const rows = await db.select().from(memoryFacts).where(where);
    return {
      facts: rows.map(toMemoryFactDto),
      server_time: new Date().toISOString(),
    };
  },

  /** Apply a batch of local changes (upserts + soft deletes by key) in one call. */
  async syncPush(userId: string, input: SyncPushInput) {
    const now = new Date();
    const facts: MemoryFactRow[] = [];
    for (const fact of input.facts) facts.push(await upsertFactRow(userId, fact, now));
    if (input.deleted_keys.length > 0) {
      await db
        .update(memoryFacts)
        .set({ deletedAt: now, updatedAt: now })
        .where(and(eq(memoryFacts.userId, userId), inArray(memoryFacts.key, input.deleted_keys)));
    }
    return {
      facts: facts.map(toMemoryFactDto),
      deleted: input.deleted_keys.length,
      server_time: now.toISOString(),
    };
  },
};
