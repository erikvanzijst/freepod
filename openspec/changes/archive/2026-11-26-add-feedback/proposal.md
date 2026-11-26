# Proposal

## Why

Freepod has no way for a person looking at a page to tell us what is wrong
with it, what they miss, or what they like, short of finding an email address
and describing the page in words. Feedback that arrives with the page, a
picture of it and the browser's recent errors is cheap to act on, and a
feedback tab on every page invites the small remarks people otherwise keep to
themselves.

## What Changes

- A **Feedback tab** on the right edge of every page of the dashboard and of
  the public pages (`/`, `/apps`, `/apps/:slug`, `/dev`), icon-only on narrow
  screens. It opens a dialog in Freepod's own styling: a required topic
  (*Something is wrong*, *An idea*, *Something else*), a message, and a
  screenshot of the page, taken when the tab was clicked, that the sender can
  remove.
- Every submission records the sender, the page (path and query, with
  secret-looking parameters removed), the browser and viewport, the commit the
  sender's UI was built from, the commit the API that stored it was built from
  (recorded by the API itself), and the page's recent console errors and failed
  API calls.
- Signed-out visitors are asked to sign in and come back to the dialog, or to
  write to `feedback@freepod.eu` instead. There is no anonymous submission.
- A deep link (`/?feedback=1`) opens the dialog without a screenshot; the
  documentation site links to it from its navbar.
- `POST /api/feedback` for any signed-in user, limited to 20 a day; admin-only
  reads, the screenshot, and marking an item resolved.
- Each submission emails the configured feedback address (prod and dev both,
  dev's subject prefixed `[dev]`) through the existing notification outbox,
  unchanged. The email names the sender; replying to it does not reach them.
- **Admin → Feedback**: a list of open items by default, an unread count on the
  sidebar entry, the full submission with its screenshot, and a Resolved
  toggle.
- The Privacy Policy names feedback, screenshots and the technical details as
  data we collect, and how long we keep them.
- Feedback is REST- and UI-only: no `caelus` commands. AGENTS.md records this
  as a parity exception.

## Capabilities

### New Capabilities

- `feedback-data-model`: what a feedback submission and its screenshot hold,
  how long they are kept, and their read and resolved state.
- `feedback-api`: submitting feedback as a signed-in user, the daily limit,
  validation of the page and screenshot, and the admin-only reads and status
  change.
- `feedback-notification`: the email each submission queues to the feedback
  address, what it carries, and the `[dev]` marker.
- `feedback-widget`: the tab, the dialog, the screenshot and its redaction, the
  diagnostics the page collects, the sign-in gate, and the deep link.
- `admin-feedback-panel`: the Admin → Feedback list, detail view, unread count
  and Resolved toggle.

### Modified Capabilities

None. The outbox and notifier are used as they are.

## Impact

- **API** (`api/`): new models and an Alembic migration (`feedback`,
  `feedback_screenshot`, seeded notification kind `feedback.submitted`);
  `app/services/feedback.py`; `app/api/feedback.py`; a `CAELUS_FEEDBACK_EMAIL`
  setting (the `[dev]` marker comes from the existing environment name).
- **UI** (`ui/`): a feedback component set (tab, dialog, screenshot capture,
  diagnostics recorder), the admin panel and route, a dependency on
  `modern-screenshot` loaded only when the tab is clicked, the API client
  reporting failed requests to the recorder, and the UI build's commit baked
  into the bundle.
- **Docs site** (`ui/docs/`): a navbar link to the deep link; a short mention of
  feedback in the user docs.
- **Terraform** (`tf/app/`): the feedback address per environment.
- **Legal** (`legal/privacy-policy.md`): data categories, purpose and retention
  for feedback; a new effective date. Only the Terms of Service version gates
  consent, so this asks no one to accept anything again.
- **AGENTS.md**: the `caelus` parity exception and a terse capability entry.
