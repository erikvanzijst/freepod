# feedback-api Specification

## Purpose

How a signed-in person submits feedback with an optional screenshot, what the platform accepts and refuses, and how administrators read submissions and mark them resolved.

## Requirements

### Requirement: Any signed-in user can submit feedback

`POST /api/feedback` SHALL accept a multipart submission from any signed-in user: a topic, a message, the page, optional context (user agent, viewport, UI build, diagnostics) and an optional screenshot file. It SHALL answer `201` with the new submission's id. An anonymous request SHALL be refused, and the route SHALL NOT be reachable without a session.

#### Scenario: Submitted with a screenshot

- **WHEN** a signed-in user posts a topic, a message, the page `/settings/handle` and a JPEG screenshot
- **THEN** the API answers `201` and stores one submission with one screenshot, sent by that user

#### Scenario: Anonymous

- **WHEN** a request without an identity posts feedback
- **THEN** it is refused and nothing is stored

### Requirement: The sender is the caller

The API SHALL take the sender and their email address from the caller's identity and SHALL ignore any sender, email or status supplied in the request.

#### Scenario: Request names another sender

- **WHEN** a signed-in user posts feedback with a form field naming another account's email
- **THEN** the submission is stored as sent by the caller, with the caller's email

### Requirement: The API records its own build

The API SHALL record on each submission the commit it was built from, as its image declares it, and SHALL ignore any API build supplied in the request. When its image declares no commit, or declares `unknown`, it SHALL record none.

#### Scenario: Built by CI

- **WHEN** an API built from commit `4eaa51e` stores a submission
- **THEN** the submission's API build is `4eaa51e`, whatever UI build the browser sent

#### Scenario: Request names an API build

- **WHEN** a request includes an API build of `deadbee`
- **THEN** it is ignored, and the submission records the API's own build

#### Scenario: Local development

- **WHEN** an API with no declared commit stores a submission
- **THEN** the submission records no API build

### Requirement: Invalid submissions are refused with a stable code

The API SHALL refuse with `422` and a stable error code a submission whose topic is unknown, whose message is empty or longer than 5000 characters, or whose page is not an absolute path on the platform's own site.

#### Scenario: Page on another site

- **WHEN** a submission names the page `https://example.com/x` or `//example.com/x`
- **THEN** it is refused with `422` and nothing is stored

#### Scenario: Message too long

- **WHEN** a submission's message has 5001 characters
- **THEN** it is refused with `422`

### Requirement: Secret-looking query parameters are removed from the page

Before storing the page, the API SHALL drop its fragment and remove every query parameter named `code`, `state`, `token`, or ending in `_token` or `secret`, keeping the rest in order.

#### Scenario: Returning from an OAuth callback

- **WHEN** a submission names the page `/settings/git?code=abc&state=xyz&installation_id=7`
- **THEN** the stored page is `/settings/git?installation_id=7`

### Requirement: A screenshot is validated and re-encoded

The API SHALL accept a screenshot only as a PNG, JPEG or WebP image of at most 2 MB and at most 4096 pixels on either side, and SHALL store it re-encoded, so that no metadata of the uploaded file is kept. Any other file SHALL be refused with `422` and nothing stored.

#### Scenario: Not an image

- **WHEN** a submission's screenshot is a PDF
- **THEN** it is refused with `422` and no submission is stored

#### Scenario: Metadata stripped

- **WHEN** a JPEG screenshot carrying EXIF data is submitted
- **THEN** the stored screenshot carries no EXIF data

### Requirement: Submissions are limited per user per day

A user SHALL be able to submit at most 20 times in any 24 hours. A further submission SHALL be refused with `429`, the code `feedback_limit`, and the time it will be accepted again.

#### Scenario: Twenty-first in a day

- **WHEN** a user who has submitted 20 times in the past 24 hours submits again
- **THEN** the API answers `429` with the code `feedback_limit` and stores nothing

### Requirement: Administrators list submissions

`GET /api/feedback` SHALL be refused to anyone but an administrator. It SHALL list submissions newest first, paged, filterable by resolved state and topic, each with its sender, topic, page, a message excerpt, whether it has a screenshot, and its read and resolved state, without screenshot data. It SHALL report the number of unread submissions.

#### Scenario: Not an administrator

- **WHEN** a user who is not an administrator lists feedback
- **THEN** the API answers `403`

#### Scenario: Open items

- **WHEN** an administrator lists unresolved submissions
- **THEN** only unresolved submissions are returned, newest first, along with the unread count

### Requirement: Administrators read one submission

`GET /api/feedback/{id}` SHALL return the whole submission to an administrator and SHALL mark it read the first time any administrator reads it. `GET /api/feedback/{id}/screenshot` SHALL return the screenshot's bytes with its media type, `404` when it has none, and SHALL be refused to anyone but an administrator.

#### Scenario: First read

- **WHEN** an administrator reads an unread submission
- **THEN** it is returned and is read from then on, and the unread count drops by one

#### Scenario: Screenshot of another's feedback

- **WHEN** a user who is not an administrator requests a submission's screenshot, even their own
- **THEN** the API answers `403`

### Requirement: Administrators resolve and reopen submissions

`PATCH /api/feedback/{id}` SHALL let an administrator set `resolved` to true, recording the time and the administrator, or to false, reopening it. Setting a submission to the state it is already in SHALL change nothing.

#### Scenario: Resolve

- **WHEN** an administrator sets a submission's `resolved` to true
- **THEN** it is resolved by that administrator at that time

#### Scenario: Resolve twice

- **WHEN** a second administrator resolves an already resolved submission
- **THEN** its resolved time and resolver are unchanged
