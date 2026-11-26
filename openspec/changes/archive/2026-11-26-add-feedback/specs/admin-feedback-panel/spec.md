# Spec Delta

## Purpose

Gives administrators one place in the admin UI to read feedback, see each submission with its page and screenshot, and keep track of what is still open.

## ADDED Requirements

### Requirement: Feedback tab in admin navigation

The admin sidebar SHALL include a *Feedback* entry that opens the feedback panel at `/admin/feedback`, gated like the rest of the admin surface. While there are unread submissions, the entry SHALL show their number.

#### Scenario: Unread feedback

- **WHEN** an administrator opens the admin area while three submissions are unread
- **THEN** the Feedback entry shows 3

#### Scenario: Nothing unread

- **WHEN** no submission is unread
- **THEN** the Feedback entry shows no number

### Requirement: The panel lists open feedback first

The panel SHALL list submissions newest first in a table showing when each was sent, its topic, its sender, its page, the start of its message, whether it has a screenshot, and whether it is unread. It SHALL show unresolved submissions by default, and SHALL let the administrator show resolved ones or all, and filter by topic.

#### Scenario: Default view

- **WHEN** an administrator opens the Feedback panel
- **THEN** only unresolved submissions are listed, unread ones marked

#### Scenario: Show resolved

- **WHEN** the administrator switches the view to resolved
- **THEN** only resolved submissions are listed

### Requirement: A submission opens in full

Selecting a submission SHALL show it in full at `/admin/feedback/:id`: the topic, the whole message, the sender's email linking to them in the users panel, when it was sent, the page as a link that opens in a new tab, the browser and viewport, the UI and API builds, the diagnostics, and the screenshot, which enlarges on click. Opening it SHALL mark it read.

#### Scenario: With a screenshot

- **WHEN** an administrator opens a submission that has a screenshot
- **THEN** the screenshot is shown and enlarges when clicked

#### Scenario: Linked directly

- **WHEN** an administrator follows the *View in Admin* link from a feedback email
- **THEN** that submission opens in full and is marked read

### Requirement: The administrator resolves, reopens and replies

The detail view SHALL offer to mark the submission resolved, or to reopen it when it is resolved, and SHALL show who resolved it and when. It SHALL offer a reply that opens the administrator's mail client addressed to the sender.

#### Scenario: Resolve

- **WHEN** an administrator marks an open submission resolved
- **THEN** it shows as resolved by them, and leaves the default list

#### Scenario: Reply

- **WHEN** an administrator chooses to reply
- **THEN** their mail client opens a message to the sender's email address
