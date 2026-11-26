# Design

## Context

Facts below were checked against the repository and freepod.eu on 2026-11-26.

- **Anonymous API calls bypass header sanitizing.** The API trusts `X-Auth-Request-Email`, which oauth2-proxy sets on every route except its `skip_auth_routes` (`tf/app/login/main.tf`). On a skipped route a client-supplied header reaches the API untouched, so the list is kept to identity-free `GET`s.
- **`/api/static` is public and immutable.** It is served by `ImmutableStaticFiles` with no identity check, and product icons live there.
- **The outbox already does most of the mail work.** `app.services.notifications.queue` inserts one row per recipient, which may be an address (`recipient_email`), in the caller's transaction. `md()` escapes interpolated values. `admin_notices` builds `https`-only action links from `settings.base_url`. The notifier (`daemons/notifier/sender.go`) writes `From`, `To` and `Subject` itself, with no `Reply-To`. Both environments' notifiers have a relay.
- **Settings the change can reuse.** `settings.environment` is `dev` or `prod`. `access_invitations_per_day` is the existing DB-counted rate limit (`app_access._check_invitation_limit`). Pillow and `python-multipart` are already API dependencies (icon upload).
- **The UI's frames.** `App.tsx` renders the public pages (`/`, `/apps`, `/apps/:slug`, `/dev`, `/legal/:slug`) outside `AppShell` and the signed-in pages inside it. Sign-in from a public page is `useStartSignup().start(path)`, which sends the browser to `/oauth2/start?rd=<origin+path>`. Every API call goes through `requestJson` in `ui/src/api/client.ts`. The commit reaches the UI image only as a runtime `GIT_COMMIT` env var in the nginx stage, not in the bundle.
- **The docs site.** `/docs` is a separate Docusaurus build served from the same origin. Its navbar takes raw HTML items (`docusaurus.config.ts`).
- **Screenshot fidelity was measured.** `modern-screenshot@4.7.0` captured the viewport of `freepod.eu/apps` in 238 ms as a 39 KB JPEG (q 0.8, scale 1), visually indistinguishable from a Playwright screenshot. Its options include `filter`, `onCloneEachNode` and `timeout`.

## Goals / Non-Goals

**Goals:**
- A screenshot never blocks or loses a submission.
- Nothing the sender types can reach an email as markup, or the database as anything but data.
- The widget adds nothing to the initial bundle beyond the tab and the dialog shell.

**Non-Goals:**
- Feedback on tenant apps or App Studio.
- `caelus` commands for feedback (D11).
- A history of their own feedback for senders, a confirmation email, or a conversation thread.
- Any change to the notification outbox or the notifier, including a `Reply-To` that would let the team answer by replying (D12).
- Full-page screenshots.

## Decisions

### D1. Signed-in only, no skip-auth route

`POST /api/feedback` is an ordinary authenticated route. Signed-out visitors get a sign-in gate and a `mailto:` link.

*Alternative:* an anonymous form. This needs a `skip_auth_routes` entry, on which a forged `X-Auth-Request-Email` arrives unsanitized, so the route would have to ignore identity entirely. It would also need its own spam defense (IP limits, a honeypot or proof-of-work) and a free-text email field nobody verifies. The mail link covers the visitor case at no cost.

### D2. The screenshot is taken in the browser, from the DOM

`modern-screenshot` (`domToJpeg`, viewport only, scale 1, quality 0.8, 5 s timeout) is `import()`ed on the tab's click, so it costs nothing until used.

*Alternatives:*
- `getDisplayMedia` produces exact pixels, but it asks the user to pick a tab in a permission prompt, and Firefox has no `preferCurrentTab`. That's a jarring step for a feedback box.
- A server-side headless render can't see the user's state, session or errors.
- `html2canvas` reimplements CSS painting and lags on modern CSS. `modern-screenshot` serializes to SVG `foreignObject`, so the browser does the painting.

### D3. The dialog opens at once; the capture excludes it

The click opens the dialog immediately and starts the capture concurrently. The capture's `filter` drops the feedback dialog's portal and backdrop, so the image shows the page as it was. The thumbnail shows a placeholder until the image is ready.

Send waits for a pending capture (at most the 5 s timeout) and then sends without it. A failed capture leaves no thumbnail and logs one diagnostics entry.

*Alternative:* capturing before opening the dialog. That makes slow devices feel unresponsive for the length of the capture.

### D4. Redaction happens in the clone

`onCloneEachNode` empties the value of every cloned `input[type=password]` and gives it, and every `[data-feedback-redact]` element, an opaque background with transparent text and children hidden. The live page is never touched, and layout is preserved because the box keeps its size.

The marker goes on the credential surfaces: the database access and SFTP credential fields, and sensitive var fields. Those are dialogs, which cover the tab anyway, so the marker is a guard for future inline uses.

### D5. Screenshots are `bytea` in their own table, re-encoded to WebP

The tables:
- `feedback_screenshot`: `feedback_id` as primary key and foreign key (`ON DELETE CASCADE`), `media_type`, `width`, `height`, `data`.
- `feedback`: everything else.

The list query never touches screenshot data. The API decodes the upload with Pillow, restricted to PNG/JPEG/WebP, checks the 2 MB and 4096 px limits, and re-encodes it as WebP (quality 85), which drops all metadata. `GET /api/feedback/{id}/screenshot` serves it with `Cache-Control: private, no-store`.

*Alternatives:*
- `/api/static` is public and immutable, which rules it out.
- Garage would need a platform bucket, credentials and a second store to keep consistent with the row, for something like 50–300 KB per item at 20 a day per user at most.

### D6. One `feedback` table with JSON context

The columns:
- `id`, `created_at`
- `user_id` (foreign key to `user`, `RESTRICT`: users are soft-deleted only), `email`
- `topic` (Postgres enum `feedback_topic`: `bug`, `idea`, `other`), `message` (`text`, `CHECK` 1–5000 characters after trimming)
- `page` (`text`), `user_agent`, `viewport` (`text`, e.g. `1440x900`), `ui_build`, `api_build`
- `diagnostics` (`jsonb`, default `[]`)
- `read_at`, `resolved_at`, `resolved_by` (foreign key to `user`)

Indexes cover `(created_at)` and the partial `(created_at) WHERE resolved_at IS NULL`.

Diagnostics stay schemaless JSON because the list is display-only. The API caps them at 20 entries, each message at 500 characters, and 32 KB overall, and drops anything else.

### D7. Page normalization lives on the server; the client does it too

The client sends `location.pathname + location.search`. On the deep link it sends the `from` parameter instead, or the referrer's path when the referrer is the same origin, or `/`.

The service rejects anything that isn't a single-slash absolute path (`//host`, schemes, backslashes). It strips the fragment and drops query keys matching `code`, `state`, `token`, `*_token`, `*secret`. The client applies the same filter before sending, so a secret never leaves the browser in the first place. The server's copy is authoritative.

### D8. Diagnostics come from a module-level ring buffer installed at startup

`main.tsx` installs one recorder before rendering. It keeps:
- `window` `error` and `unhandledrejection` events (message and source location)
- `console.error` calls, wrapped to keep a string summary and still call the original
- reports from `requestJson`: a response with status ≥ 400, or a network failure, recorded as method, the path without its query string, and status

It keeps 20 entries, which the dialog reads on Send. The API client reports explicitly rather than having `fetch` monkey-patched, so third-party requests aren't recorded.

### D9. One widget mounted at the app root

A `FeedbackProvider` inside the router and `AuthProvider` in `App.tsx` owns the dialog state, the deep-link handling and the single `FeedbackTab`. It hides the tab on `/legal/*`.

Mounting it once covers the public pages and `AppShell` without touching `Dashboard.tsx`, `Admin.tsx` or each landing page, and the tab can't be duplicated or forgotten on a new page. Components go under `ui/src/components/feedback/`:
- the tab
- the dialog
- the sign-in gate
- the screenshot thumbnail
- the capture helper
- the diagnostics recorder

### D10. The deep link and the sign-in round trip use the same URL

`?feedback=1[&from=…]` on any page opens the dialog without a screenshot. Closing it `replace`s the URL without those parameters.

The gate's *Sign in* calls `start(currentPath + '?feedback=1&from=' + page)`, so oauth2-proxy returns the visitor to the same page with the dialog open. A screenshot can't survive the redirect, so a returning visitor's dialog has none.

The docs navbar adds the raw HTML item `<a href="/?feedback=1">Feedback</a>`. The app reads the docs page from `document.referrer`, which is same-origin and therefore carries the full path. The docs build needs no client code and no swizzled component.

### D11. No `caelus` commands

Feedback is submitted from a page, and triage is reading screenshots. Neither has a meaningful terminal form, and operators with database access can query the tables. This joins the documented exceptions in AGENTS.md § Conventions. As with the others, the rules live in `app/services/feedback.py`, so REST and the admin UI share them.

### D12. The email uses the outbox as it is

The migration seeds the kind `feedback.submitted` (not unsubscribable), the way earlier kinds were added. `submit_feedback` calls `notifications.queue` with `email=` set to the feedback address, in the same transaction as the insert. The outbox schema, its grants and the notifier stay untouched.

The body names the sender's email address. The admin detail view's *Reply* is a `mailto:` link to the sender.

*Alternative:* a `reply_to` column on the outbox, sent as `Reply-To`, so hitting Reply in a mail client answers the sender. Rejected to keep this change from spilling into the shared notification mechanism: it needs a schema change, a notifier release, and a rollout order between the two.

The feedback address comes from the new setting `CAELUS_FEEDBACK_EMAIL`. Empty means no email, which is the default for local development and tests. Tf sets `feedback@freepod.eu` in both workspaces. The subject is `[<environment>] ` when the environment isn't `prod`, then `Feedback · <topic label>: <message, first line, ≤ 60 chars, ellipsized>`.

### D13. Unread count rides on the list response

`GET /api/feedback` returns `{items, total, unread}`. The sidebar badge reads the unread count from a small `?limit=0` query, cached by react-query and refetched on window focus and after any feedback mutation. It's fetched only inside the admin area, so non-admins never request it.

*Alternative:* a separate count endpoint. That's one more route for the same query.

### D14. Both builds are recorded: the UI's from the bundle, the API's from itself

`scripts/build-images.sh`, which CI also runs, passes `GIT_COMMIT=$(git rev-parse --short HEAD)` to both the UI and API image builds. Today the UI uses it only as a runtime env var in its nginx stage, and the API has it as a runtime env var.

- **UI.** The builder stage takes the build arg as `VITE_GIT_COMMIT`, so it is baked into the bundle, and the dialog sends it as `ui_build`, or `dev` when it's absent. It is the code the sender's browser was actually running: a tab left open across a deploy reports the old commit.
- **API.** The service reads `GIT_COMMIT` from its own environment, the way `caelus catalog apply` already does, and stores it as `api_build`, null when absent or `unknown`. The request has no say in it. The two can differ: dev runs hand-pushed branch images, and either image can be rolled back alone.

A hand build from a tree with uncommitted changes still reports HEAD's commit. CI builds from clean checkouts, so only manual dev builds are affected, and marking them `-dirty` would need a variable separate from the image tag the script derives from the same commit. Left as is.

## Risks / Trade-offs

- **Imperfect screenshots of unusual content** (Monaco, DataGrid virtualization, MUI X charts, cross-origin images): DOM capture can render these imperfectly. → Capture failure never blocks sending (D3), and all icons are same-origin. Check the admin template editor, a DataGrid panel and the usage charts on dev during implementation.
- **Slow capture on low-end phones**: → The dialog opens first, and the capture has a 5 s timeout.
- **Screenshots show whatever was on screen**, including other users' data when an administrator sends feedback from Admin. → Screenshots are readable by administrators only, served `no-store`, and named in the Privacy Policy.
- **Wrapping `console.error` changes the call stack** shown in devtools for that one frame. → The wrapper calls the original with the same arguments. It's acceptable for the value.
- **A feedback address on dev mails a shared inbox**: → The `[dev]` subject prefix (spec), and dev traffic is small.

## Migration Plan

1. Merge with the migration, API and UI code, and the feedback address set in `tf/app`.
2. Apply `tf/app` on dev (`default` workspace). The API init container runs `alembic upgrade head`. Smoke test:
   - submit from the dashboard and from `/apps` after signing in
   - check the email's `[dev]` subject, sender and *View in Admin* link
   - check the Admin panel, the badge and resolve
3. Apply on prod.
4. Rollback: revert the UI image to drop the tab. The API routes are inert without callers. The migration's downgrade drops both tables, the enum and the kind.
