import { createMiddleware } from "hono/factory";

export type User = { id: string; email: string; name: string };
export type AuthEnv = { Variables: { user: User | null } };

const DEV_USER: User = { id: "dev-user", email: "dev@localhost", name: "Developer" };

// "Sign in with Freepod": once enabled for the deployment, every request
// carries the signed-in user in these headers (the platform strips any that a
// client sends itself). X-Freepod-User is the stable id; key your data on it.
// Without the headers, development mode acts as a fixed developer account.
export const currentUser = createMiddleware<AuthEnv>(async (c, next) => {
  const id = c.req.header("x-freepod-user");
  let user: User | null = null;
  if (id) {
    user = {
      id,
      email: c.req.header("x-freepod-email") ?? "",
      name: decodeURIComponent(c.req.header("x-freepod-name") ?? ""),
    };
  } else if (process.env.NODE_ENV !== "production") {
    user = DEV_USER;
  }
  c.set("user", user);
  await next();
});

// For routes that only signed-in users may call.
export const requireUser = createMiddleware<AuthEnv>(async (c, next) => {
  if (!c.get("user")) return c.json({ error: "Sign in required" }, 401);
  await next();
});
