# feedback-data-model Specification

## Purpose

What a feedback submission records about its message, its sender and the page it was sent from, how its screenshot is held apart from it, and the read and resolved state administrators track.

## Requirements

### Requirement: A submission records its message and topic

Each feedback submission SHALL hold a non-empty message of at most 5000 characters and exactly one topic: `bug` (shown as *Something is wrong*), `idea` (*An idea*) or `other` (*Something else*), and the time it was received.

#### Scenario: Unknown topic

- **WHEN** a submission is stored with the topic `praise`
- **THEN** the database refuses it

#### Scenario: Empty message

- **WHEN** a submission is stored with a message that is empty or only whitespace
- **THEN** it is refused

### Requirement: A submission records its sender

Each submission SHALL reference the account that sent it and SHALL keep the email address that account held when it was sent. Deleting the account SHALL NOT delete or alter its submissions.

#### Scenario: Sender changes email afterwards

- **WHEN** Ana sends feedback and then changes their email address
- **THEN** the submission still shows the address Ana held when sending it, and still references Ana's account

#### Scenario: Sender's account deleted

- **WHEN** the account that sent a submission is deleted
- **THEN** the submission, its sender reference and its email address are kept

### Requirement: A submission records where it was sent from

Each submission SHALL hold the page it was sent from as a path with its query, without a fragment and without an origin. It SHALL hold the sender's user agent, viewport size and the UI build identifier, each when the client supplied it, the client's diagnostics as a list, and the build identifier of the API that stored it, when the API knows it.

#### Scenario: Sent from an app page

- **WHEN** feedback is sent from `https://freepod.eu/apps/immich?tab=plans#pricing`
- **THEN** the submission records the page `/apps/immich?tab=plans`

#### Scenario: No diagnostics

- **WHEN** a client sends no diagnostics
- **THEN** the submission records an empty list

### Requirement: A screenshot is held apart from its submission

A submission SHALL have at most one screenshot, stored apart from the submission so that listing submissions does not read screenshot data. A screenshot SHALL record its media type and its pixel dimensions, and SHALL be deleted with its submission.

#### Scenario: Submission without a screenshot

- **WHEN** a submission is stored without a screenshot
- **THEN** it is accepted and reports that it has no screenshot

#### Scenario: Second screenshot

- **WHEN** a second screenshot is stored for a submission that already has one
- **THEN** the database refuses it

### Requirement: Submissions are kept

Submissions and their screenshots SHALL NOT expire or be purged by the platform.

#### Scenario: Old submission

- **WHEN** a submission is two years old
- **THEN** it and its screenshot are still stored

### Requirement: A submission tracks whether it was read and resolved

A submission SHALL record when an administrator first opened it, if ever, and when it was resolved and by whom, if it is resolved. Both are shared by all administrators. A resolved submission SHALL be able to be reopened, which clears its resolved time and resolver.

#### Scenario: New submission

- **WHEN** a submission is stored
- **THEN** it is unread and unresolved

#### Scenario: Reopened

- **WHEN** an administrator reopens a resolved submission
- **THEN** it is unresolved, with no resolved time or resolver, and stays read
