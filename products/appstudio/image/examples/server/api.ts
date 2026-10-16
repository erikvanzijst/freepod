import { Hono } from "hono";
import { currentUser, type AuthEnv } from "./auth";
import { filesRoutes } from "./routes/files";
import { notesRoutes } from "./routes/notes";

// The app's API, mounted at /api. Larger areas get their own file in
// server/routes/ and are mounted here.
export const api = new Hono<AuthEnv>();

api.use(currentUser);

api.get("/health", (c) => c.json({ ok: true }));

api.get("/me", (c) => c.json({ user: c.get("user") }));

api.route("/notes", notesRoutes);
api.route("/files", filesRoutes);
