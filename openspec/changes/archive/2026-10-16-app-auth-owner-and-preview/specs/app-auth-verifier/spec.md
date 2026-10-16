# Spec Delta

## ADDED Requirements

### Requirement: Allowed accounts
A deployment's edge configuration MAY restrict which signed-in accounts reach the app, by listing allowed email addresses alongside its public paths. When a list is present, a request carrying a valid session whose email is not on it SHALL NOT reach the app, on any path, public paths included. Emails SHALL match case-insensitively. Without a list, every signed-in account is allowed, as before.

#### Scenario: Allowed account
- **WHEN** the list is `["alice@example.com"]` and a request carries Alice's valid session, signed in as `Alice@Example.com`
- **THEN** the request reaches the app with Alice's identity headers

#### Scenario: Other account
- **WHEN** the list is `["alice@example.com"]` and a request carries Bob's valid session
- **THEN** the request does not reach the app; a navigation receives the no-access page (see *The no-access page*), and any other request receives `403`

#### Scenario: Public path under an allow list
- **WHEN** the list is `["alice@example.com"]`, `/` is public, and Bob's valid session asks for `/`
- **THEN** the request does not reach the app

#### Scenario: Anonymous request under an allow list
- **WHEN** the list is `["alice@example.com"]` and a request without a session asks for a public path
- **THEN** the request reaches the app with no identity headers

### Requirement: An unreadable allow list admits no one
If the allowed-accounts list is present but cannot be read, the verifier SHALL treat it as allowing no account, so a signed-in request never reaches the app through it.

#### Scenario: Corrupt list
- **WHEN** the edge configuration carries an allowed-accounts value that is not a valid list
- **THEN** signed-in requests are refused as for an account not on the list

### Requirement: The no-access page
A refused navigation SHALL receive `403` with a page in the look of the platform's placeholder page for a deployment without an app. It SHALL name the application and its address (`https://<host>`), say that the signed-in account (by email) has no access, and offer signing out to switch accounts. The application's name SHALL come from the edge configuration when present, and otherwise be the host.

#### Scenario: Named application
- **WHEN** the edge configuration names the application "App Studio" and Bob is refused on `studio.alice.freepod.eu`
- **THEN** the page names "App Studio" and `https://studio.alice.freepod.eu`, says `bob@example.com` has no access, and links to sign out

#### Scenario: Unnamed application
- **WHEN** the edge configuration gives no name and Bob is refused on `notes.alice.freepod.eu`
- **THEN** the page names the application as `notes.alice.freepod.eu`
