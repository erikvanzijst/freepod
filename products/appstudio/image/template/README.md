# App

A Freepod app: TypeScript, one Node process serving the API (Hono) and the
frontend (React, Vite, Tailwind, shadcn/ui), with PostgreSQL through Drizzle.
Working code for common features (records per user, file uploads, sign-in)
is in `/opt/appstudio/examples`: read it and copy what you need.

## Run it

```bash
npm install
dev-app                       # App Studio: runs it with a local database and S3,
                              # live at $APPSTUDIO_PREVIEW_URL, with hot reload
```

Without App Studio: set `DATABASE_URL` (and the `AWS_*` variables for S3), then
`PORT=8080 npm run dev`.

`npm run build && npm start` runs it as Freepod does. `npm run check` type-checks.

## Layout

| Path | What |
|------|------|
| `server/index.ts` | Startup: migrations, then the server on `$PORT` (with Vite in development) |
| `server/api.ts` | The API, mounted at `/api`; larger areas go in `server/routes/` |
| `server/auth.ts` | The signed-in user from Sign in with Freepod; `requireUser` for private routes |
| `server/same-origin.ts` | Refuses data changes sent from other sites' pages; no other site may frame the app |
| `server/db/schema.ts` | Tables; after a change, `npm run db:generate` writes a migration to `drizzle/` |
| `server/storage.ts` | The app's S3 bucket |
| `src/config.ts` | The app's name |
| `src/App.tsx` | The pages (one route each), inside the app shell |
| `src/components/app-shell.tsx` | Header, page frame and footer around every page |
| `src/pages/` | The pages; `home.tsx` is a placeholder to replace |
| `src/components/ui/` | shadcn/ui components |
| `DESIGN.md` | How the frontend should look |

## Rules that keep it deployable

- Keep the `start` script. Without it, Freepod's builder serves `dist/` as a
  static site and the API never runs. Never start production with `vite` or
  `vite preview`.
- Every setting comes from the environment (`DATABASE_URL`, `AWS_*`,
  `S3_BUCKET`, the app's own vars); nothing is hardcoded or committed.
- Schema changes go through migrations in `drizzle/`, which run at startup.
- Nothing written to the local disk survives a restart; files go to S3.
