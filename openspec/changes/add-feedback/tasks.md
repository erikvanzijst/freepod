# Tasks

## 1. Data model

- [ ] 1.1 Add `FeedbackORM` (including `ui_build` and `api_build`), `FeedbackScreenshotORM` and the `feedback_topic` enum under `api/app/models/` (design D5, D6) and export them; verify `uv run --no-sync python -c "import app.models"` succeeds
- [ ] 1.2 Write one Alembic migration: both feedback tables, the enum, indexes, and the seeded notification kind `feedback.submitted` (not unsubscribable), with a downgrade that removes all of it; verify `alembic upgrade head`, `downgrade -1` and `upgrade head` all succeed against the local Postgres
- [ ] 1.3 Add data-model tests: unknown topic and blank message refused, second screenshot refused, screenshot cascades with its submission, a soft-deleted sender keeps their submissions; verify they pass

## 2. Feedback service and API

- [ ] 2.1 Add `feedback_email` (`CAELUS_FEEDBACK_EMAIL`, default empty) and `feedback_per_day` (20) to `app/config.py`; verify the settings tests pass
- [ ] 2.2 Implement page normalization in `app/services/feedback.py` (D7); verify with unit tests for the fragment, the secret-parameter list, `//host`, schemes, backslashes and relative paths
- [ ] 2.3 Implement screenshot processing (Pillow PNG/JPEG/WebP only, 2 MB, 4096 px, re-encode to WebP) beside `app/services/images.py`; verify tests for a PDF, an oversize file, oversized dimensions, and EXIF stripped
- [ ] 2.4 Implement diagnostics sanitizing (20 entries, 500 characters each, 32 KB) and verify it with a test
- [ ] 2.5 Implement `submit_feedback` (sender from the caller, `api_build` from the API's own `GIT_COMMIT` and null when absent or `unknown` (D14), the DB-counted 24 h limit raising `RateLimitedException` code `feedback_limit`, the notification queued through the unchanged `notifications.queue` in the same transaction when `feedback_email` is set, with the subject format, `[env]` prefix, escaped body and the https-only *View in Admin* action); verify tests for each feedback-notification scenario, each scenario of the API-build requirement (env set, `unknown`, unset, spoofed form field) and the 21st submission
- [ ] 2.6 Implement `list_feedback` (paged, resolved/topic filters, `unread`, no screenshot bytes), `get_feedback` (marks read on first read), `get_screenshot` and `set_resolved` (idempotent, records resolver, reopen clears); verify service tests
- [ ] 2.7 Add `app/api/feedback.py` routes (`POST` multipart for any signed-in user; `GET` list and detail, `GET …/screenshot` with `Cache-Control: private, no-store`, `PATCH` for admins), register the router, and map `feedback_limit` to 429 and validation codes to 422; verify API tests cover every feedback-api scenario, including caller-spoofing form fields, anonymous refused and 403 for non-admins
- [ ] 2.8 Confirm no `skip_auth_routes` entry is needed (none added) and that the client-version gate and origin guard accept the multipart `POST`; verify with an API test using the UI's headers
- [ ] 2.9 Run the full `api/` suite (`uv run --no-sync pytest`, default `-n 8`) and verify it is green

## 3. Feedback widget (UI)

- [ ] 3.1 Add `modern-screenshot@4.7.0` to `ui/package.json` and verify that `npm run build` shows it only in a lazily loaded chunk
- [ ] 3.2 Bake `GIT_COMMIT` into the bundle as `VITE_GIT_COMMIT` in the builder stage of `ui/Dockerfile` (D14); verify `docker build --build-arg GIT_COMMIT=abc123` yields a bundle containing `abc123`
- [ ] 3.3 Implement the diagnostics recorder (`ui/src/components/feedback/diagnostics.ts`: error and rejection listeners, a `console.error` wrapper, a 20-entry ring) and have `requestJson` report failed responses and network errors without query strings; install it in `main.tsx`; verify Vitest tests for ordering, the cap, method/path/status-only API entries and the original `console.error` still being called
- [ ] 3.4 Implement the capture helper (lazy import, viewport JPEG, `filter` excluding the feedback dialog, `onCloneEachNode` redaction of password inputs and `[data-feedback-redact]`, 5 s timeout, failure resolves to no screenshot); verify Vitest tests with the library mocked, covering the filter, redaction and failure
- [ ] 3.5 Mark `data-feedback-redact` on the database-access and SFTP credential fields and on `SensitiveVarField`; verify those components' existing tests still pass
- [ ] 3.6 Implement `FeedbackTab` (right-edge vertical tab in Freepod styling, icon-only below 600 px, focusable, labeled *Feedback*), `FeedbackDialog` (the three required topic chips, message, thumbnail with enlarge and remove, the disclosure line, Send waiting on a pending capture, a thank-you state that closes on its own, errors kept in place with the `feedback_limit` retry time) and `FeedbackSignInGate` (sign in via `useStartSignup().start` with `?feedback=1&from=…`, plus a `mailto:feedback@freepod.eu` link); verify Vitest tests for each feedback-widget dialog scenario
- [ ] 3.7 Implement `FeedbackProvider` and mount it once in `App.tsx` (D9): tab hidden on `/legal/*`, `?feedback=1[&from=]` opening the dialog without a screenshot, page resolution order `from` → same-origin referrer → `/`, closing removes the parameters; verify Vitest tests for the routes, the deep link and the referrer fallback
- [ ] 3.8 Add the endpoint functions and types to `ui/src/api/endpoints.ts`/`types.ts` (multipart submit) and verify `npm run build` and `npm run lint` pass

## 4. Admin feedback panel

- [ ] 4.1 Add the *Feedback* entry with the unread badge to `AdminSidebar` and routes `/admin/feedback` and `/admin/feedback/:id` in `App.tsx` (lazy, like the other panels); verify a Vitest test that the badge shows the unread count and hides at 0
- [ ] 4.2 Implement `FeedbackPanel` (DataGrid newest first, open/resolved/all and topic filters, unread marker, screenshot indicator) and `FeedbackDetail` (full message, sender linked to the users panel, page opening in a new tab, browser/viewport, UI and API builds, diagnostics, zoomable screenshot, resolve/reopen with resolver and time, reply as `mailto:`); verify Vitest tests for the default open filter, opening an item (marks read, badge drops) and resolve/reopen
- [ ] 4.3 Run `npm test`, `npm run lint` and `npm run build` in `ui/` and verify all pass

## 5. Docs, legal, infra

- [ ] 5.1 Add the `<a href="/?feedback=1">Feedback</a>` navbar item to `ui/docs/docusaurus.config.ts`, mention the Feedback tab in `ui/docs/apps/getting-help.md` (American English, present tense, no internals); verify `npm run build` in `ui/docs` succeeds
- [ ] 5.2 Update `legal/privacy-policy.md`: feedback (message, screenshot, page, browser and technical details) under §2 *Support data*, its purpose and legal basis in §3, its retention in §7, and a new effective date; verify the UI legal-content tests (`npm test`) still pass the version guard
- [ ] 5.3 Set `CAELUS_FEEDBACK_EMAIL = "feedback@freepod.eu"` for the API in `tf/app` (both workspaces); verify `terraform validate` and a `terraform plan` on the `default` workspace showing only that change
- [ ] 5.4 AGENTS.md: add feedback to the § Conventions `caelus` parity exceptions (REST/UI only, D11) and a terse capability entry with spec and design links; verify the links resolve

## 6. Integration on dev

- [ ] 6.1 Deploy to dev (images built from a branch with an explicit tag; tf `default` workspace) and verify on dev.freepod.eu:
  - signed-in submission from the dashboard, Settings and `/apps` with a screenshot
  - the signed-out gate round trip on `/apps`
  - the docs navbar link naming the docs page
  - the email arriving at feedback@freepod.eu with `[dev]`, the sender named and a working *View in Admin* link
  - the Admin badge, detail, screenshot and resolve
- [ ] 6.2 Check screenshot fidelity on the admin template editor (Monaco), a DataGrid panel, the usage charts and a phone-width viewport; record anything off in the PR

## Workflow follow-up

- Open the PR; after merge, roll out to prod and repeat 7.1's email and Admin checks there.
- Archive the change (syncing specs) once it is live on both environments.
