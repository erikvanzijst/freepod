import { pgTable, serial, text, timestamp } from "drizzle-orm/pg-core";

// Rows that belong to a person are keyed on X-Freepod-User (user.id), the
// stable account id, never on the email address, which can change.
export const notes = pgTable("notes", {
  id: serial("id").primaryKey(),
  userId: text("user_id").notNull(),
  body: text("body").notNull(),
  createdAt: timestamp("created_at", { withTimezone: true }).notNull().defaultNow(),
});
