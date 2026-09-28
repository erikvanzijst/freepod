## MODIFIED Requirements

### Requirement: Reserved sign-in paths

On every auth-enabled app host, the verifier SHALL answer every path under `/.freepod/auth/` itself, and none of them SHALL reach the app. At least these SHALL exist:
- `/.freepod/auth/login?rd=<path>`: starts sign-in and returns to `<path>` afterwards.
- `/.freepod/auth/callback`: completes sign-in (see *Sign-in completes on the app's own host*).
- `/.freepod/auth/logout?rd=<path>`: signs out (see *Logout ends the Freepod sign-in*) and returns to `<path>` afterwards.

Unknown paths under the prefix SHALL receive `404`. A return target SHALL be accepted only if it is a path on the same host: it starts with a single `/`, and is neither protocol-relative (`//`) nor a backslash variant. Otherwise the return target SHALL be `/`.

Every redirect the verifier issues SHALL use an absolute `https://` URL. Relative locations are not safe to use, because the edge resolves them against the verifier's own in-cluster address.

#### Scenario: App links to sign-in

- **WHEN** a page's "Sign in" link points at `/.freepod/auth/login?rd=/lists`
- **THEN** the browser starts sign-in and, once it completes, lands on `https://<host>/lists`

#### Scenario: Open-redirect attempt

- **WHEN** a request asks for `/.freepod/auth/login?rd=//evil.example/`
- **THEN** the return target becomes `/`

#### Scenario: Open-redirect attempt on logout

- **WHEN** a request asks for `/.freepod/auth/logout?rd=//evil.example/`
- **THEN** the return target carried through sign-out is `/`

#### Scenario: App cannot shadow reserved paths

- **WHEN** the app itself serves a route at `/.freepod/auth/login`
- **THEN** requests to that path never reach the app

## ADDED Requirements

### Requirement: Logout ends the Freepod sign-in

`/.freepod/auth/logout` SHALL expire `__Host-freepod_session` on the requesting host. It SHALL then redirect the browser to the broker's sign-out for that host, carrying the return target, so that the user's Freepod sign-in at the identity provider ends as well (see the broker's *Signing out at the identity provider*). Once sign-out completes, the browser SHALL land on the return target on the same host.

Logout SHALL NOT expire sessions on other hosts. A user signed in to other apps SHALL stay signed in to them until those sessions expire or the user logs out of them.

After logout, the next sign-in on any app SHALL ask the user to authenticate at the identity provider, where they MAY choose a different account. Sign-ins after that one SHALL again need no interaction, as long as the new identity-provider sign-in lasts.

#### Scenario: Log out and sign in as someone else

- **WHEN** Alice, signed in to `milk.erik.freepod.eu`, opens `/.freepod/auth/logout?rd=/` and confirms signing out, and `/` is protected
- **THEN** she lands on the identity provider's sign-in form rather than back in the app as Alice
- **AND** signing in there as Bob returns her to `https://milk.erik.freepod.eu/` as Bob

#### Scenario: Other apps keep their session

- **WHEN** Alice, signed in to both `milk.erik.freepod.eu` and `notes.erik.freepod.eu`, logs out of `milk`
- **THEN** her session on `notes` still works

#### Scenario: One sign-in after logout

- **WHEN** Alice logs out of `milk`, signs in again, and later opens `docs.erik.freepod.eu`, an app she has no session for but has consented to
- **THEN** she reaches `docs` without entering credentials

#### Scenario: Logout with a public return target

- **WHEN** a deployment declares `public: ["^/$"]` and Alice opens `/.freepod/auth/logout?rd=/`
- **THEN** after signing out she lands on `https://<host>/` with no identity headers reaching the app

## REMOVED Requirements

### Requirement: Logout ends the session on one host

**Reason**: Ending only the host's session let the next navigation re-issue a session for the same account without any prompt, because the identity-provider sign-in survived. Logout had no visible effect on protected paths, and a user could not switch accounts.
**Migration**: None needed by apps. `/.freepod/auth/logout?rd=<path>` keeps its URL and parameters. Its behavior is now *Logout ends the Freepod sign-in*: it still leaves other hosts' sessions alone, and it now also ends the identity-provider sign-in.
