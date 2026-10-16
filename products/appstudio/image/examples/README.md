# Examples

The App Studio starter (`/opt/appstudio/template`) with working features added,
to read and copy from: never run it in place of the user's app. Every file
follows the starter's layout, so a pattern lands in the same place in the app.

| To build | Read |
|----------|------|
| Records that belong to the signed-in user | `server/db/schema.ts`, `server/routes/notes.ts`, `src/pages/notes.tsx` |
| A migration for a new table | `drizzle/0000_notes.sql` (written by `npm run db:generate`) |
| File uploads and downloads (S3) | `server/routes/files.ts`, `src/pages/files.tsx` |
| Pages only for signed-in users | `src/components/sign-in-required.tsx`, used in both pages above |
| Mounting route files in the API | `server/api.ts` |
| Several pages with navigation | `src/App.tsx`, `src/components/app-shell.tsx` |
| A landing page with entry points | `src/pages/home.tsx` |
| Loading, empty and error states | `src/pages/notes.tsx`, `src/pages/files.tsx` |

The starter's `README.md` covers running, the layout and deploy rules, and
`DESIGN.md` the look.
