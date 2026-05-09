import { drizzle } from "drizzle-orm/postgres-js";
import { readdir, readFile } from "node:fs/promises";
import { join } from "node:path";
import postgres from "postgres";
import { env } from "../config/index.js";
import { logger } from "../utils/logger.js";
import * as schema from "./schema/index.js";

const databaseUrl = new URL(env.DATABASE_URL);
const isSupabaseHost = databaseUrl.hostname.endsWith(".supabase.co");
const useSsl = env.DATABASE_SSL_ENABLED
  ? env.DATABASE_SSL_ENABLED === "true"
  : isSupabaseHost;

const client = postgres(env.DATABASE_URL, {
  max: 10,
  idle_timeout: 20,
  connect_timeout: 10,
  ...(useSsl ? { ssl: "require" as const } : {}),
});

export const db = drizzle(client, { schema });
export { client as sql };

const migrationCandidates = [
  join(process.cwd(), "src/core/db/migrations"),
  join(process.cwd(), "dist/core/db/migrations"),
];
const migrationTableName = "__app_migrations";
const migrationLockId = 90241017;
const migrationTableSql = `"${migrationTableName}"`;

const resolveMigrationsDirectory = async () => {
  for (const candidate of migrationCandidates) {
    try {
      const entries = await readdir(candidate, { withFileTypes: true });
      if (entries.some((entry) => entry.isFile() && entry.name.endsWith(".sql"))) {
        return {
          directory: candidate,
          files: entries
            .filter((entry) => entry.isFile() && entry.name.endsWith(".sql"))
            .map((entry) => entry.name)
            .sort(),
        };
      }
    } catch {
      continue;
    }
  }

  throw new Error(`No SQL migrations found. Checked: ${migrationCandidates.join(", ")}`);
};

export const verifyDatabaseConnection = async () => {
  await client`select 1`;

  logger.info(
    {
      host: databaseUrl.hostname,
      ssl: useSsl,
    },
    "Database connection ready",
  );
};

export const runDatabaseMigrations = async () => {
  if (env.DATABASE_AUTO_MIGRATE === "false") {
    logger.info("Automatic database migrations disabled");
    return;
  }

  const { directory, files } = await resolveMigrationsDirectory();

  await client.begin(async (tx) => {
    await tx`select pg_advisory_xact_lock(${migrationLockId})`;
    const migrationTable = (await tx.unsafe(
      `select to_regclass('public.${migrationTableName}') as exists`,
    )) as Array<{ exists: string | null }>;

    if (!migrationTable[0]?.exists) {
      await tx.unsafe(`
        create table ${migrationTableSql} (
          "name" text primary key,
          "applied_at" timestamp default now() not null
        )
      `);
    }

    const appliedRows = (await tx.unsafe(`select "name" from ${migrationTableSql}`)) as Array<{ name: string }>;
    const applied = new Set(appliedRows.map((row) => row.name));

    for (const file of files) {
      if (applied.has(file)) {
        continue;
      }

      const sql = await readFile(join(directory, file), "utf8");
      await tx.unsafe(sql);
      await tx.unsafe(`insert into ${migrationTableSql} ("name") values ($1)`, [file]);

      logger.info({ file }, "Applied database migration");
    }
  });
};
