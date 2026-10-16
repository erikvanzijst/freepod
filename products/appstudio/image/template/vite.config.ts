import path from "node:path";
import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: { alias: { "@": path.resolve(import.meta.dirname, "src") } },
  // Development only: in App Studio the dev server is reached through the
  // preview hostname, which Vite would otherwise refuse.
  server: { allowedHosts: true },
});
