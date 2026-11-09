# Spec Delta

## Purpose

The platform's one sender of notifications: how it finds queued notifications, renders them in Freepod's layout, delivers them by email, and records how each one ended.

## ADDED Requirements

### Requirement: Queued notifications are sent promptly

The sender SHALL begin delivering a notification within seconds of the transaction that queued it committing, while the sender is running and connected to the database.

#### Scenario: Invitation queued

- **WHEN** the API commits an access-list addition and its invitation
- **THEN** the sender starts delivering the invitation within five seconds

### Requirement: No pending notification is left behind

The sender SHALL send every notification that is `pending` when it starts, and SHALL find pending notifications on its own at least once a minute, so that a wake-up lost while it was stopped or disconnected delays a notification by at most a minute after it is running and connected again.

#### Scenario: Queued while the sender was down

- **WHEN** notifications are queued while the sender is stopped, and it then starts
- **THEN** it sends them

#### Scenario: Wake-up lost

- **WHEN** the sender's database connection drops, a notification is queued meanwhile, and the connection is restored
- **THEN** the notification is sent within a minute

### Requirement: Each notification is delivered by one sender

When more than one sender runs, each pending notification SHALL be attempted by only one of them at a time, and a notification SHALL NOT be sent again once it is terminal. A sender that stops during a delivery SHALL leave the notification `pending`, so it may be delivered twice but is never lost.

#### Scenario: Two replicas

- **WHEN** two senders run while a notification is queued
- **THEN** it is delivered once

#### Scenario: Sender killed mid-delivery

- **WHEN** a sender is killed after handing a message to the relay and before recording it
- **THEN** the notification is still `pending` and is delivered again

### Requirement: Failed attempts are retried briefly, then recorded

The sender SHALL retry a delivery that fails, up to three attempts in all, a few seconds apart, and then mark the notification `failed` with the error of the last attempt. A failed notification SHALL NOT be retried unless it is set back to `pending`.

#### Scenario: Relay hiccup

- **WHEN** the first attempt is refused and the second succeeds
- **THEN** the notification is `sent` with two attempts

#### Scenario: Relay down

- **WHEN** all three attempts fail
- **THEN** the notification is `failed`, records the last error, and is not attempted again

### Requirement: Without a relay, notifications are suppressed

When the sender has no relay configured, it SHALL mark each pending notification `suppressed` without attempting delivery.

#### Scenario: Development environment

- **WHEN** a notification is queued in an environment whose sender has no relay configured
- **THEN** it becomes `suppressed` and nothing is sent

### Requirement: An unreachable recipient fails

A notification addressed to a user whose record holds no email address SHALL be marked `failed` without a delivery attempt, saying so.

#### Scenario: User without an address

- **WHEN** a notification is addressed to a user with no email address
- **THEN** it is `failed` with an error naming the missing address

### Requirement: The sender owns the layout

Every email SHALL be sent from the platform's configured sender address in Freepod's branded layout: the heading, or the subject when there is none, then the rendered body, then the action as a button when there is one, then a footer with the notification's reason. Each email SHALL carry a plain-text part with the same content.

#### Scenario: Full notification

- **WHEN** a notification with a heading, a body, an action and a reason is sent
- **THEN** the HTML part shows them in that order in the Freepod layout, and the plain-text part holds the body, the action's URL and the reason

#### Scenario: No action

- **WHEN** a notification without an action is sent
- **THEN** the email shows no button

### Requirement: The body is rendered as Markdown, without markup

The sender SHALL render the body as CommonMark. It SHALL NOT pass raw HTML in the body through to the email, and SHALL NOT render a link or image whose URL scheme is other than `https`, `http` or `mailto`. The heading, subject, action label and reason SHALL be treated as plain text.

#### Scenario: Link in the body

- **WHEN** a body contains `[the app](https://cloud.freepod.app)`
- **THEN** the email shows a link to `https://cloud.freepod.app`

#### Scenario: Raw HTML in the body

- **WHEN** a body contains `<img src=x onerror=alert(1)>`
- **THEN** the email contains no such element

#### Scenario: Script link

- **WHEN** a body contains `[click](javascript:alert(1))`
- **THEN** the email contains no link to that URL

#### Scenario: Markup in the heading

- **WHEN** a heading contains `<b>Hi</b>`
- **THEN** the email shows those characters as text
