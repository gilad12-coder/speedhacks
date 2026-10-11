import { readFile } from "node:fs/promises";
import postgres from "postgres";

const sql = postgres(process.env.DATABASE_URL, { max: 1 });
await sql.unsafe(await readFile(new URL("../db/schema.sql", import.meta.url), "utf8"));
await sql.end();
console.log("schema applied");
