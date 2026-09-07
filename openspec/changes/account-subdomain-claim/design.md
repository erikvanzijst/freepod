## Context

See proposal.md — Why. The state that shapes the approach:

- The platform already has a user-level fact that is NULL until settled and required before
  deploying: Terms of Service acceptance. It is recorded through its own resource
  (`POST /api/me/tos-acceptance`), enforced at exactly one call site in
  `api/app/services/deployments.py`, surfaced in the deploy dialog only for users who have
  not settled it, and explicitly *not* gated at authentication
  (`openspec/specs/cli-terms-acceptance/spec.md`). Every structural decision below is that
  pattern applied again.
- `require_valid_hostname_for_deployment` (`api/app/services/hostnames.py`) runs an ordered,
  short-circuiting sequence of checks and raises one exception carrying a reason code, which
  `GET /api/hostnames/{fqdn}` returns verbatim to an unauthenticated caller. The UI's
  `HostnameField` already consumes it with a 400 ms debounce, so the claim dialog's live
  validation is an existing pattern rather than a new one.
- `UserORM` carries a partial unique index over `lower(email)` where `deleted_at IS NULL`.
  The subdomain index is that index again.
- Deployment hostnames today are a single label under `freepod.eu`, and
  `_check_wildcard_depth` actively refuses a second label. This change does not touch that.

Interaction design, mockups and a working prototype of the dialog:
<https://claude.ai/code/artifact/359c879f-7851-47a2-b869-dc25448cc756>

## Goals / Non-Goals

**Goals:**

- Every account that can deploy holds one permanent label, chosen by its owner.
- The choice is made once, understood when it is made, and cannot be silently undone.
- The change is safe to merge and deploy on its own, with the hostname scheme unchanged.

**Non-Goals:**

- Deriving deployment hostnames from the subdomain. Deployments keep landing at
  `<app>.freepod.eu` until the hostname change lands separately.
- Per-user TLS certificates, DNS, and everything downstream of the two-label scheme.
- Migrating existing deployments, and assigning subdomains to existing accounts. Both are a
  one-off operator task, deliberately out of scope.
- Any way to change or release a subdomain, including for administrators.
- A CLI claim flow.

## Decisions

### D1: Freepod owns the label, not Keycloak

The registration form already collects a username, so the cheap option was to make that the
subdomain and forward it as a header. Rejected on two grounds, the first decisive:

- **Availability is a question only Freepod can answer.** It depends on the reserved list,
  on labels other accounts hold, and on the deployments table. Keycloak can express a
  character-class rule and realm-wide uniqueness; everything else would need a custom Java
  validator calling this API from inside the registration transaction, which puts Freepod's
  availability on the critical path of signing up.
- **The registration form validates on submit.** A rejected username returns the page with
  the password fields cleared, which is a poor way to tell someone the name they wanted is
  taken.

The consequence is that the Keycloak username has no remaining job, and the realm should
stop collecting one (`registrationEmailAsUsername`). That is a realm configuration change,
tracked separately from this one.

### D2: Enforced at deployment creation, not at authentication

Gating `get_current_user` would centralize the check, but it would put a new error class on
every authenticated endpoint, break `get_optional_user` (which delegates to it, and serves
endpoints that are public but shaped by identity), and require an exemption list that must
stay in sync with two others — the FastAPI public routes and oauth2-proxy's
`skip_auth_routes`, a pair `api/README.md` already calls a footgun.

The precondition is not "using the platform", it is "creating a deployment", which is where
ToS acceptance is enforced and for the same reason. Clients still need to handle the
refusal, so the gate would not have saved them work either.

### D3: One list of reserved names, derived rather than duplicated

A candidate is refused when `<label>.<wildcard domain>` is already in `reserved_hostnames`.
The alternative — a `reserved_subdomains` setting — was rejected because the two lists would
hold the same names for the same reason and drift apart the first time only one was updated.
If a name ever needs reserving as a subdomain but not as a hostname, it goes in the same
list; reserving a hostname nobody could deploy to costs nothing.

### D4: The claim is not idempotent

A second claim is a 409 even when it submits the label the account already holds. A repeated
claim is far more likely to be a client that lost track of its state than a user who meant
it, and the endpoint that silently succeeds is the one that hides the bug.

### D5: A claimed label is refused as a deployment hostname

This is what makes the change independently deployable. Until the hostname scheme moves,
deployments are still created at `<label>.freepod.eu`, so without this check a deployment
could take `alice.freepod.eu` while `alice` is somebody's subdomain — and every application
that account later deploys would sit beneath a name a stranger's app answers.

It is refused for the holder too. The label names the account's namespace, not any one
deployment in it, and letting the holder park an app there would collide with their own
applications the moment the scheme changes.

The check goes after `reserved` and before availability: it is a question about accounts
rather than deployments, so it is answered before the deployments table is consulted.

### D6: The odometer rests on a placeholder, and stops

The animation exists to make one thing legible in a second: the left-hand slot is a space
the user is being given, not a field they must fill. Two constraints follow, and both were
found by watching it rather than by reasoning:

- **It must not rest on a real name.** Coming to rest on `wiki` asserts that the user picked
  it and that it is theirs. The home slot is a placeholder, set in the UI face and italic
  where the tumbling names are monospaced, so the distinction is carried by typeface and
  needs nothing read.
- **It must be slow enough to read.** The easing matters more than the duration: a quartic
  ease-out spends almost all its travel in the opening rush, so only the final name is
  legible. Cubic over ~2.6 s spends roughly 40% of the spin on the last name and 10% on the
  one before it.

After settling it stops. Ambient motion beside a field somebody is typing their name into is
an irritation that never resolves into anything readable. It re-runs once when a typed label
is first found available — motion as feedback, fired after the debounce so it never moves
under the cursor — and on demand.

### D7: The confirmation shows the fully qualified name, and no application label

The confirmation freezes one thing, so it shows exactly that thing and all of it:
`alice.freepod.eu`, entire and emphasized. The platform domain is being set in stone
alongside the label, and a user who reads only the emphasized part must still be reading
something true. An application label on that screen implies a second decision is being
taken; it belongs on the screen after, where it is an invitation.

### D8: The CLI refuses rather than prompting

The client can reach the availability endpoint, so an inline prompt was possible. It would
be a second implementation of a one-time screen — its own validation, permanence warning and
confirmation, maintained forever — for the users who reach the platform through the terminal
first, and it cannot carry the animation that makes the decision comprehensible. It refuses,
names the cause, and points at the browser, which is the fallback the terms-acceptance spec
already reaches for when it cannot present an agreement.

The deploy is abandoned rather than suspended. The alternative is holding a packed archive
against a decision being made in another window; the cost is one re-run of a command that is
in the user's shell history.

## Risks / Trade-offs

- **The dialog's promise is ahead of the platform.** "Everything you deploy lives under this
  address" is not true until the hostname scheme changes: in the interim a claimed subdomain
  reserves a name and changes no address. → See Migration Plan; this is a sequencing
  constraint on release, not on implementation.
- **The prefill nudges people toward their own name, which reaches certificate transparency
  logs permanently** once they deploy. Accepted deliberately in favor of the shortest path
  for a general audience; mitigated only by the dialog stating that the address is public.
- **Permanence with no escape hatch means support tickets** about typos and regretted names,
  answered by an operator editing the database or by nothing. Accepted: every mechanism for
  changing one is a mechanism for breaking somebody's addresses, and the alternative
  interacts badly with certificates, links and federated applications.
- **Existing accounts.** Everyone who has already deployed holds no subdomain and would be
  refused their next deployment. → The operator assigns subdomains to existing accounts as
  part of the separate migration; until that runs, this change's gate must not be enabled on
  an environment with existing users. Noted in the plan below.
- **A claim races another claim.** Two users can be told the same label is available and both
  submit. → The unique index decides; the loser gets a refusal and the dialog stays open with
  the name marked taken. The check is advisory by nature and cannot be made otherwise.

## Migration Plan

1. Schema and API first: the column, its index, the claim and read endpoints, and the
   hostname check. Inert on their own — nothing calls them, and no user-visible behavior
   changes.
2. The UI and the CLI refusal, then the deployment-create precondition. The precondition is
   the only step that changes what an existing user can do, so it lands last.
3. **Release ordering.** On an environment with existing users, step 2's precondition MUST
   NOT be enabled before those accounts hold subdomains — otherwise their next deployment is
   refused with a dialog that has nothing to say to them. The operator's assignment pass and
   the hostname migration are separate work; this change is complete and mergeable before
   either, and its last step is held for them.
4. The dialog's copy is written in the present tense and is accurate from the moment the
   hostname scheme lands. If the claim is released to users before that, the two sentences
   promising that deployed apps live under the address are the only text that needs a
   temporary future tense.

**Rollback:** the column is additive and the endpoints are new, so reverting the API image
restores previous behavior with claims intact and inert. Only the deployment-create
precondition is observable, and removing it is a one-line revert.
