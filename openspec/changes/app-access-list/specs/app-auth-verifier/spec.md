# Spec Delta

## ADDED Requirements

### Requirement: List changes reach the verifier within 30 seconds

The verifier SHALL apply an access list no older than 30 seconds. When it is about to refuse a signed-in request and its copy of the list is more than 5 seconds old, it SHALL read the list again before deciding. Neither SHALL need a reconcile or a restart.

#### Scenario: Removal

- **WHEN** the owner removes Ana from a `listed` header app while Ana has a valid session
- **THEN** within 30 seconds Ana's requests are refused

#### Scenario: Addition just before signing in

- **WHEN** the owner adds Noor, and Noor signs in and opens the app within the next few seconds
- **THEN** Noor's requests reach the app

## MODIFIED Requirements

### Requirement: Allowed accounts

A deployment's edge configuration MAY say that the deployment's access list applies. When it does, a request carrying a valid session SHALL reach the app only when the session belongs to the deployment's owner or to an account the access list admits, on any path, public paths included. The owner SHALL be recognized by email, case-insensitively. Without that setting, every signed-in account is allowed, as before.

#### Scenario: Allowed account

- **WHEN** the access list applies, Alice is on it, and a request carries Alice's valid session
- **THEN** the request reaches the app with Alice's identity headers

#### Scenario: Owner

- **WHEN** the access list applies and is empty, and a request carries the owner's valid session
- **THEN** the request reaches the app with the owner's identity headers

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

### Requirement: An unreadable allow list admits no one

If the verifier cannot read a deployment's access list, it SHALL keep using the last copy it read, however old. If it has never read one since it started, it SHALL admit no signed-in account to that deployment until it can.

#### Scenario: Database outage

- **WHEN** the database becomes unreachable while the verifier holds a copy of a deployment's list
- **THEN** it keeps admitting and refusing by that copy

#### Scenario: Corrupt list

- **WHEN** the edge configuration's setting for the access list has a value the verifier does not recognize
- **THEN** signed-in requests are refused as for an account not on the list

#### Scenario: Started during an outage

- **WHEN** the verifier starts while the database is unreachable, and a signed-in request arrives for a deployment whose access list applies
- **THEN** the request is refused as for an account not on the list

### Requirement: The no-access page

A refused navigation SHALL receive `403` with a page in the look of the platform's placeholder page for a deployment without an app. It SHALL name the application and its address (`https://<host>`), say that it is open only to the people its owner has added and that the signed-in account (by email) is not among them, suggest asking whoever shared the link to add that address, and offer signing out to switch accounts. The application's name SHALL come from the edge configuration when present, and otherwise be the host.

#### Scenario: Named application

- **WHEN** the edge configuration names the application "App Studio" and Bob is refused on `studio.alice.freepod.eu`
- **THEN** the page names "App Studio" and `https://studio.alice.freepod.eu`, says `bob@example.com` has no access, and links to sign out

#### Scenario: Unnamed application

- **WHEN** the edge configuration gives no name and Bob is refused on `notes.alice.freepod.eu`
- **THEN** the page names the application as `notes.alice.freepod.eu`
