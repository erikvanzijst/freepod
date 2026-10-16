import { drizzle } from "drizzle-orm/postgres-js";
import { migrate } from "drizzle-orm/postgres-js/migrator";
import postgres from "postgres";
import * as schema from "./schema";

const url = process.env.DATABASE_URL;
if (!url) {
  throw new Error(
    'DATABASE_URL is not set. Freepod sets it for a deployed app; in App Studio run: eval "$(dev-postgres)"',
  );
}

// prepare: false because Freepod's connection pooler does not keep the
// session state named prepared statements need. onnotice silences notices such
// as "already exists, skipping" from every startup migration.
const client = postgres(url, { max: 5, prepare: false, onnotice: () => {} });

export const db = drizzle(client, { schema });

// Freepod has no release phase, so migrations run here, before the server
// starts listening.
export async function migrateDatabase() {
  await migrate(db, { migrationsFolder: "drizzle" });
}
