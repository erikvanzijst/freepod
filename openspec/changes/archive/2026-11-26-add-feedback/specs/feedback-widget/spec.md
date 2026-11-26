# Spec Delta

## Purpose

The Feedback entry point on Freepod's pages: the tab, the dialog in which a person writes feedback with a screenshot of the page, the technical details sent along, the sign-in gate for visitors, and the link that opens it from elsewhere.

## ADDED Requirements

### Requirement: A Feedback tab sits on every page

A Feedback tab SHALL be fixed to the right edge of the viewport, vertically centered, on every page of the signed-in dashboard and on the public pages `/`, `/apps`, `/apps/:slug` and `/dev`. On viewports narrower than 600 pixels it SHALL show only an icon. It SHALL NOT appear on `/legal/*` pages. It SHALL be keyboard-focusable and announced as *Feedback*.

#### Scenario: Dashboard

- **WHEN** a signed-in user views the dashboard
- **THEN** the Feedback tab is on the right edge

#### Scenario: Phone

- **WHEN** a page is viewed 390 pixels wide
- **THEN** the tab shows an icon and no text, and still opens the dialog

#### Scenario: Legal document

- **WHEN** someone views `/legal/privacy`
- **THEN** there is no Feedback tab

### Requirement: The dialog takes a topic and a message

The tab SHALL open a dialog in Freepod's styling with three topic choices, *Something is wrong*, *An idea* and *Something else*, none chosen at first, and a message field. Send SHALL stay disabled until a topic is chosen and the message holds more than whitespace. The dialog SHALL state that the account, the page, the screenshot when kept, and technical details are sent along.

#### Scenario: No topic

- **WHEN** a user writes a message without choosing a topic
- **THEN** Send is disabled

#### Scenario: Sent

- **WHEN** a user chooses a topic, writes a message and presses Send
- **THEN** the feedback is submitted, the dialog thanks them in place of the form, and then closes on its own

### Requirement: The dialog keeps the message when sending fails

When a submission fails, the dialog SHALL keep the topic, message and screenshot and show the platform's error, including the time a rate-limited user may send again.

#### Scenario: Rate limited

- **WHEN** a submission is refused with `feedback_limit`
- **THEN** the dialog shows when feedback can be sent again and the message is still in the field

### Requirement: A screenshot of the page is taken when the tab is clicked

Clicking the tab SHALL capture the visible part of the page as it was before the dialog opened, and the dialog SHALL show it as a thumbnail that enlarges on click. The screenshot SHALL be included by default, and the sender SHALL be able to remove it before sending. When capture fails or is unavailable, the dialog SHALL open without one and feedback SHALL still be sendable.

#### Scenario: Default

- **WHEN** a user opens the dialog and sends without touching the thumbnail
- **THEN** the screenshot is submitted, and it does not show the dialog

#### Scenario: Removed

- **WHEN** a user removes the thumbnail before sending
- **THEN** no screenshot is submitted

#### Scenario: Capture fails

- **WHEN** the screenshot cannot be taken
- **THEN** the dialog opens without a thumbnail and Send works

### Requirement: Secrets are blanked in the screenshot

The screenshot SHALL show password fields, and every element the UI marks as sensitive, as blank areas of the same size.

#### Scenario: Password field on screen

- **WHEN** a password field holding a value is visible when the tab is clicked
- **THEN** the screenshot shows a blank area where the field's content was

### Requirement: The page's recent problems are sent along

From the moment the UI loads, it SHALL keep the 20 most recent uncaught errors, console errors and failed platform API calls, each with its time; an API call as method, path and status only, never a body or header. A submission SHALL include them without listing them in the dialog.

#### Scenario: Failed request before feedback

- **WHEN** a request to the platform API answered `500` and the user then sends feedback
- **THEN** the submission includes that request's method, path and status, and no request or response body

#### Scenario: Many errors

- **WHEN** 30 errors occurred before feedback is sent
- **THEN** the submission includes the 20 most recent

### Requirement: The page sent is the page the user is on

A submission SHALL name the current page's path and query. When the dialog was opened by the feedback link, it SHALL name the page given in the link, or else the platform page the user came from, or else `/`.

#### Scenario: From a deployment's settings

- **WHEN** a user opens the dialog on `/settings/ssh-keys`
- **THEN** the submission names `/settings/ssh-keys`

#### Scenario: From the documentation

- **WHEN** a user follows the documentation's Feedback link from `/docs/developers/deploying`
- **THEN** the submission names `/docs/developers/deploying`

### Requirement: Visitors are asked to sign in

For a visitor who is not signed in, the dialog SHALL NOT offer the form. It SHALL explain that feedback is sent from an account, offer to sign in, and offer `feedback@freepod.eu` as a mail link. Signing in from it SHALL return the visitor to the page they were on with the dialog open.

#### Scenario: Visitor on the catalog

- **WHEN** a visitor who is not signed in clicks the tab on `/apps`
- **THEN** the dialog offers to sign in or to email `feedback@freepod.eu`, and no form

#### Scenario: Signing in from the dialog

- **WHEN** the visitor signs in from the dialog
- **THEN** they come back to `/apps` with the feedback dialog open, without a screenshot

### Requirement: A link opens the dialog

Any platform page opened with the query parameter `feedback=1` SHALL open the dialog without a screenshot; a `from` parameter, when present, SHALL name the page. The documentation site's navbar SHALL link to it.

#### Scenario: Link with a page

- **WHEN** a signed-in user opens `/?feedback=1&from=/apps/immich`
- **THEN** the dashboard shows with the dialog open, naming `/apps/immich`, without a screenshot

#### Scenario: Closing the dialog

- **WHEN** the user closes a dialog that the link opened
- **THEN** `feedback` and `from` are removed from the address bar
