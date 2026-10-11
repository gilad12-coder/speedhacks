import "server-only";
import postgres from "postgres";
import { env } from "./env";

// Reuse one pool across hot reloads in dev and across invocations of a warm function.
const globalForDb = globalThis as unknown as { sql?: postgres.Sql };

export const sql: postgres.Sql =
  globalForDb.sql ?? postgres(env.databaseUrl, { max: 5, prepare: false });

if (process.env.NODE_ENV !== "production") globalForDb.sql = sql;
