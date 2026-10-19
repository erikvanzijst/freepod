import { createMiddleware } from "hono/factory";

// Sent with every page and API response: only the app itself may show it in a
// frame, and browsers take each response's content type as given.
export const pageHeaders: Record<string, string> = {
  "content-security-policy": "frame-ancestors 'self'",
  "x-frame-options": "SAMEORIGIN",
  "x-content-type-options": "nosniff",
};

const SAFE_METHODS = new Set(["GET", "HEAD", "OPTIONS"]);

// True when a page on another origin made the browser send this request.
// Requests from outside a browser (curl, webhooks) carry neither header.
function fromOtherOrigin(headers: Headers): boolean {
  const site = headers.get("sec-fetch-site");
  if (site) return site !== "same-origin" && site !== "none";
  const origin = headers.get("origin");
  if (!origin) return false;
  try {
    return new URL(origin).host !== headers.get("host");
  } catch {
    return true;
  }
}

// Refuses requests that change data when another origin's page sent them, and
// adds pageHeaders to every response that has not set them itself.
export const sameOrigin = createMiddleware(async (c, next) => {
  if (!SAFE_METHODS.has(c.req.method) && fromOtherOrigin(c.req.raw.headers)) {
    return c.json({ error: "Cross-origin request refused" }, 403);
  }
  await next();
  for (const [name, value] of Object.entries(pageHeaders)) {
    if (!c.res.headers.has(name)) c.header(name, value);
  }
});
