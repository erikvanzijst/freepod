## Purpose

Which runs of the upgrade service send an email, to whom, and through what. The owner
hears about a run only when it has something for them to act on.

## ADDED Requirements

### Requirement: A noteworthy run sends one email
When a run completes with at least one product whose outcome is `opened`, `would_open`,
`failed` or `timed_out`, the service MUST send one email to `NOTIFY_EMAIL`. The email
lists every product's outcome and versions. It names each pull request, or would-be pull
request, with the decisions it leaves to a human, and gives each failure's error. When
`DASHBOARD_URL` is set, it links to the run's dashboard page.

A run whose products all ended as `up_to_date`, `skipped` or `would_skip` MUST NOT send
an email. Neither does a run that did not complete — one interrupted by a restart, or one
the owner canceled — nor any run while `NOTIFY_EMAIL` is unset.

#### Scenario: Everything is up to date
- **WHEN** a run completes with every product `up_to_date`
- **THEN** no email is sent

#### Scenario: A dry run would open a pull request
- **WHEN** a dry run completes with `vaultwarden` as `would_open` and the others up to date
- **THEN** one email is sent to `NOTIFY_EMAIL`, naming the would-be `vaultwarden` pull request and its target version

#### Scenario: A draft that needs decisions
- **WHEN** a real run opens a draft pull request whose result lists decisions needing a human
- **THEN** the email links the pull request and lists those decisions

#### Scenario: A product fails
- **WHEN** a run completes with one product `timed_out`
- **THEN** one email is sent naming that product and its outcome

#### Scenario: A canceled run
- **WHEN** the owner cancels a run whose running product had already been recorded `would_open`
- **THEN** no email is sent, because the run did not complete

#### Scenario: No recipient
- **WHEN** a noteworthy run completes while `NOTIFY_EMAIL` is unset
- **THEN** no email is sent, and the run is recorded as it would be otherwise

### Requirement: Mail goes through the shared relay, and a failed send changes no outcome
The service MUST send mail over SMTP on port 25 to `SMTP_HOST`, whose default is the
platform's shared relay, from the address `NOTIFY_FROM`.

A failure to send MUST be logged, and MUST NOT change the recorded outcome of the run or
of any of its products.

#### Scenario: The relay refuses the message
- **WHEN** the relay rejects or cannot be reached for a noteworthy run's email
- **THEN** the failure appears in the service's log
- **AND** the run is recorded as `completed`, with its products' outcomes unchanged
