import { createServer } from "node:http";
import { getRequestListener, serve } from "@hono/node-server";
import { serveStatic } from "@hono/node-server/serve-static";
import { Hono } from "hono";
import { api } from "./api";
import { migrateDatabase } from "./db";
import { pageHeaders, sameOrigin } from "./same-origin";

// Freepod tells the app which port to bind; App Studio's preview is port 8080.
const port = Number(process.env.PORT ?? 8080);
const hostname = "0.0.0.0";
const production = process.env.NODE_ENV === "production";

await migrateDatabase();

const app = new Hono();
app.use(sameOrigin);
app.route("/api", api);

if (production) {
  // The frontend, built by `npm run build` into dist/.
  app.use("/*", serveStatic({ root: "./dist" }));
  app.get("*", serveStatic({ path: "./dist/index.html" }));
  serve({ fetch: app.fetch, port, hostname }, () => {
    console.log(`Listening on http://${hostname}:${port}`);
  });
} else {
  // Development: one process, like production. The API goes to Hono and
  // everything else to Vite, with hot reload over the same port.
  const { createServer: createVite } = await import("vite");
  const server = createServer();
  const vite = await createVite({
    server: { middlewareMode: true, ws: { server } },
    appType: "spa",
  });
  const handleApi = getRequestListener(app.fetch);
  server.on("request", (req, res) => {
    if (req.url?.startsWith("/api/")) return handleApi(req, res);
    for (const [name, value] of Object.entries(pageHeaders)) res.setHeader(name, value);
    vite.middlewares(req, res);
  });
  server.listen(port, hostname, () => {
    console.log(`Development server on http://${hostname}:${port}`);
  });
}
