## MODIFIED Requirements

### Requirement: Allowed accounts

A deployment's edge configuration MAY say that the deployment's access list applies. When it does, a request carrying a valid session SHALL reach the app only when the session belongs to the deployment's owner or to an account the access list admits, on any path, public paths included. The owner SHALL be recognized by the subject stored on the owner's user record and, only while that record carries no subject, by email, case-insensitively. Without that setting, every signed-in account is allowed, as before.

#### Scenario: Allowed account

- **WHEN** the access list applies, Alice is on it, and a request carries Alice's valid session
- **THEN** the request reaches the app with Alice's identity headers

#### Scenario: Owner

- **WHEN** the access list applies and is empty, and a request carries the owner's valid session
- **THEN** the request reaches the app with the owner's identity headers

#### Scenario: Owner with a changed email

- **WHEN** the access list applies, the owner's record carries their subject, and a request carries the owner's valid session with an email the record does not hold
- **THEN** the request reaches the app with the owner's identity headers

#### Scenario: Owner's email under another subject

- **WHEN** the access list applies, the owner's record carries a subject, and a request carries the valid session of a different subject whose email equals the owner's stored email
- **THEN** the request does not reach the app

#### Scenario: Other account

- **WHEN** the access list applies and a request carries the valid session of Bob, who is neither the owner nor listed
- **THEN** the request does not reach the app; a navigation receives the no-access page (see *The no-access page*), and any other request receives `403`

#### Scenario: Public path under an allow list

- **WHEN** the access list applies, `/` is public, and Bob's valid session asks for `/`
- **THEN** the request does not reach the app

#### Scenario: Anonymous request under an allow list

- **WHEN** the access list applies and a request without a session asks for a public path
- **THEN** the request reaches the app with no identity headers

#### Scenario: Preview hostname

- **WHEN** the access list of `studio-alice.freepod.app` applies and Bob's valid session asks for `preview-studio-alice.freepod.app`
- **THEN** the request does not reach the preview
