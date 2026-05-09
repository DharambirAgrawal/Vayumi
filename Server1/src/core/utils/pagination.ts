import { z } from "zod";

export const paginationQuerySchema = z.object({
  limit: z.coerce.number().int().min(1).max(100).default(25),
  offset: z.coerce.number().int().min(0).default(0),
  cursor: z.string().optional(),
});

export type PaginationQuery = z.infer<typeof paginationQuerySchema>;

export const paginated = <T>(items: T[], input: Pick<PaginationQuery, "limit" | "offset">) => ({
  items,
  page: {
    limit: input.limit,
    offset: input.offset,
    count: items.length,
  },
});
