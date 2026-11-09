# Spec Delta

## Purpose

The outbox through which platform services hand messages for people to one sender: what a queued notification holds, who may queue one, how duplicates are refused, and how each ends up recorded.

## ADDED Requirements

### Requirement: A notification has one recipient

Each queued notification SHALL be addressed to exactly one recipient: either a Freepod user or an email address, never both and never neither. A message for several people SHALL be queued as one notification per person.

#### Scenario: Two recipients

- **WHEN** a producer has the same message for two people
- **THEN** it queues two notifications, each with its own state

#### Scenario: Neither or both

- **WHEN** a producer queues a notification naming both a user and an address, or neither
- **THEN** the database refuses it

### Requirement: A user recipient is reached at their current address

A notification addressed to a Freepod user SHALL be delivered to the email address the user's record holds when it is sent, not when it was queued. A notification addressed to an email address SHALL be delivered to that address. Notifications addressed to a user SHALL be deleted with the user.

#### Scenario: Address changed while queued

- **WHEN** a notification for Ana is queued and Ana changes their email before it is sent
- **THEN** it is delivered to their new address

#### Scenario: Account deleted

- **WHEN** a user's account is deleted
- **THEN** no notification addressed to that user remains

### Requirement: A notification carries its content and its reason

A notification SHALL hold a subject, a Markdown body and the reason the recipient receives it, and MAY hold a heading and an action, a label with an absolute `https` URL, given together or not at all. The body SHALL be the producer's, and the layout around it SHALL be the sender's.

#### Scenario: Action without a URL

- **WHEN** a producer queues a notification with an action label and no URL
- **THEN** the database refuses it

#### Scenario: No heading

- **WHEN** a notification is queued without a heading
- **THEN** it is accepted

### Requirement: Every notification has a known kind

A notification SHALL name its kind, such as `access.invitation`, from a list of kinds kept in the database. Each kind SHALL record whether recipients could unsubscribe from it. A notification of a kind not on the list SHALL be refused.

#### Scenario: Misspelled kind

- **WHEN** a producer queues a notification of kind `access.invitaton`
- **THEN** the database refuses it

#### Scenario: Seeded kinds

- **WHEN** the outbox is created
- **THEN** the kinds `access.invitation` and `database.quota` exist, neither unsubscribable

### Requirement: The database records the origin

Each notification SHALL record as its origin the database role that queued it. A producer SHALL NOT be able to set or change the origin.

#### Scenario: Producer names another origin

- **WHEN** a producer other than the table's owner queues a notification with an origin of its own choosing
- **THEN** the database refuses it

#### Scenario: Origin recorded

- **WHEN** the role `caelus_app_auth` queues a notification
- **THEN** its origin is `caelus_app_auth`

### Requirement: A dedupe key queues a message once

A producer MAY give a notification a dedupe key. At most one notification SHALL exist per kind and dedupe key, whatever its state. Notifications without a dedupe key SHALL never conflict with one another.

#### Scenario: Retried producer

- **WHEN** a producer queues a notification with dedupe key `entry:42` and then queues it again with the same kind and key
- **THEN** only the first is kept

#### Scenario: No key

- **WHEN** two identical notifications are queued without a dedupe key
- **THEN** both are kept

#### Scenario: Same key, other kind

- **WHEN** two notifications of different kinds use the same dedupe key
- **THEN** both are kept

### Requirement: Each notification ends in one recorded state

A notification SHALL be queued `pending` and SHALL end in exactly one terminal state: `sent`, `failed` when every attempt failed, or `suppressed` when the environment does not deliver. It SHALL record its number of attempts, the time it was queued, the time it was sent, and the error of its last failed attempt. A terminal notification SHALL be kept.

#### Scenario: Delivered

- **WHEN** a notification is delivered
- **THEN** it is `sent`, with its send time and attempt count

#### Scenario: Undeliverable

- **WHEN** every attempt to deliver a notification fails
- **THEN** it is `failed` and records the last error

### Requirement: Producers may only queue

A platform role granted the producer columns SHALL be able to queue notifications, and SHALL NOT be able to read, change or delete notifications, or change the list of kinds. Only the sender's role SHALL be able to change a notification's delivery state.

#### Scenario: Producer reads the outbox

- **WHEN** a producer role selects from the outbox
- **THEN** the database refuses it

#### Scenario: Producer marks a notification sent

- **WHEN** a producer role updates a notification's state
- **THEN** the database refuses it

### Requirement: A pending notification raises a wake-up

The database SHALL raise a notification on a fixed channel whenever a notification is queued or returns to `pending`, delivered when its transaction commits. Producers SHALL NOT need to raise it themselves. A rolled-back queueing SHALL raise nothing.

#### Scenario: Queued

- **WHEN** a producer commits a transaction that queues a notification
- **THEN** a listener on the channel is woken

#### Scenario: Requeued by hand

- **WHEN** an operator sets a `failed` notification back to `pending`
- **THEN** a listener on the channel is woken

#### Scenario: Rolled back

- **WHEN** a transaction that queued a notification rolls back
- **THEN** no listener is woken and no notification remains
