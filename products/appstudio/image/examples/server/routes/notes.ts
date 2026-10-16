import { and, desc, eq } from "drizzle-orm";
import { Hono } from "hono";
import { requireUser, type AuthEnv } from "../auth";
import { db } from "../db";
import { notes } from "../db/schema";

// A signed-in user's own records: every query is scoped to user.id.
export const notesRoutes = new Hono<AuthEnv>();

notesRoutes.use(requireUser);

notesRoutes.get("/", async (c) => {
  const user = c.get("user")!;
  const rows = await db.select().from(notes).where(eq(notes.userId, user.id)).orderBy(desc(notes.createdAt));
  return c.json(rows);
});

notesRoutes.post("/", async (c) => {
  const user = c.get("user")!;
  const { body } = await c.req.json<{ body?: string }>();
  if (!body?.trim()) return c.json({ error: "Write something first." }, 400);
  const [note] = await db.insert(notes).values({ userId: user.id, body: body.trim() }).returning();
  return c.json(note, 201);
});

notesRoutes.delete("/:id", async (c) => {
  const user = c.get("user")!;
  const id = Number(c.req.param("id"));
  await db.delete(notes).where(and(eq(notes.id, id), eq(notes.userId, user.id)));
  return c.body(null, 204);
});
