# Spec Delta

## ADDED Requirements

### Requirement: Ended sessions reach the verifier within 10 seconds

The verifier SHALL apply a copy of the ended Keycloak sessions no older than 10 seconds, without a reconcile or a restart. When the database cannot be read, it SHALL keep using its last copy. Until it has read the ended sessions once, it SHALL NOT pass any signed-in request to an app.

#### Scenario: Sign-out elsewhere

- **WHEN** a user's Keycloak session ends while they hold a header-app session from it
- **THEN** within 10 seconds their requests to that app are treated as having no session

#### Scenario: Database outage

- **WHEN** the database becomes unreachable after the verifier has read the ended sessions
- **THEN** sessions that were valid stay valid, and sessions ended before the outage stay refused

#### Scenario: Never read

- **WHEN** the verifier starts while the database is unreachable
- **THEN** signed-in requests to header apps receive an error and the apps see no requests

## MODIFIED Requirements

### Requirement: Session validity

A session SHALL be valid only when all of the following hold:
- the `__Host-freepod_session` cookie was issued by this environment's app authentication and has not been altered;
- it was issued for the exact host the request is addressed to;
- it has not expired;
- the Keycloak session it was issued from, when it names one, has not ended.

A session SHALL expire no later than 7 days after issue. A session issued for one host SHALL NOT be accepted on any other host, including another host of the same owner. A session issued in one environment SHALL NOT be accepted in the other.

#### Scenario: Cookie replayed on another app

- **WHEN** a valid session cookie issued for `milk.erik.freepod.eu` is sent to `notes.erik.freepod.eu`
- **THEN** the verifier treats the request as having no session

#### Scenario: Expired session

- **WHEN** a session cookie issued 7 days and one minute ago is presented
- **THEN** the verifier treats the request as having no session

#### Scenario: Tampered cookie

- **WHEN** any byte of a session cookie's value is altered
- **THEN** the verifier treats the request as having no session

#### Scenario: Keycloak session ended

- **WHEN** a session cookie names a Keycloak session that has since ended
- **THEN** the verifier treats the request as having no session
