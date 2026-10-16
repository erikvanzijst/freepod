import { Hono } from "hono";
import { currentUser, type AuthEnv } from "./auth";

// The app's API, mounted at /api. Add routes here or in their own files.
export const api = new Hono<AuthEnv>();

api.use(currentUser);

api.get("/health", (c) => c.json({ ok: true }));

api.get("/me", (c) => c.json({ user: c.get("user") }));
