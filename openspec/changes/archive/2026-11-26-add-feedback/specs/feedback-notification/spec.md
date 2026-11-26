# Spec Delta

## Purpose

The email every feedback submission sends to the platform's feedback address, so the team reads feedback where it reads mail. The email is an ordinary platform notification; replying to it does not reach the sender.

## ADDED Requirements

### Requirement: Each submission emails the feedback address

When an environment has a feedback address configured, storing a submission SHALL queue, in the same transaction, one notification of kind `feedback.submitted` to that address. Without a configured address, no notification SHALL be queued and the submission SHALL still be stored. The kind SHALL NOT be unsubscribable.

#### Scenario: Production

- **WHEN** feedback is submitted in an environment whose feedback address is `feedback@freepod.eu`
- **THEN** one `feedback.submitted` notification addressed to `feedback@freepod.eu` is queued with it

#### Scenario: No address configured

- **WHEN** feedback is submitted in an environment with no feedback address
- **THEN** the submission is stored and nothing is queued

#### Scenario: Submission refused

- **WHEN** a submission is refused for any reason
- **THEN** no notification is queued

### Requirement: The email carries the submission

The subject SHALL name the topic and begin the message. The body SHALL hold the whole message, the sender's email and handle, the page as a link on the platform's own site, the browser, the UI and API builds, and whether a screenshot was attached. Every value the sender supplied SHALL be escaped so it renders as text. The screenshot SHALL NOT be attached.

#### Scenario: Markup in the message

- **WHEN** a message contains `[click](https://evil.example)` and `<b>`
- **THEN** the email shows those characters as text, with no link to `evil.example`

#### Scenario: Subject

- **WHEN** an *An idea* submission begins "Let me pick the region for my app"
- **THEN** the subject names the topic and begins with that message, shortened when long

### Requirement: The email links to the submission in Admin

When the platform's own address is `https`, the notification SHALL carry the action *View in Admin*, linking to that submission in the Admin feedback panel. Otherwise it SHALL carry no action.

#### Scenario: Local development

- **WHEN** feedback is submitted where the platform is served over plain `http`
- **THEN** the notification has no action

### Requirement: Mail from outside production is marked

In every environment other than production, the subject SHALL begin with the environment's name in brackets.

#### Scenario: Development

- **WHEN** feedback is submitted on the development environment
- **THEN** the subject begins with `[dev]`

#### Scenario: Production

- **WHEN** feedback is submitted on production
- **THEN** the subject has no bracketed prefix
