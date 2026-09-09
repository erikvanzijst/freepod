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
  `GET /api/hostnames/{fqdn}` returns verbatim to the caller. The UI's `HostnameField`
  already consumes it with a 400 ms debounce, so the claim dialog's live validation reuses
  an existing pattern rather than inventing one.
- `UserORM` carries a partial unique index over `lower(email)` where `deleted_at IS NULL`.
  The subdomain index is that index again.
- Deployment hostnames today are a single label under a wildcard domain, and
  `_check_wildcard_depth` actively refuses a second label. This change inverts that rule.
- Nothing derives a hostname server-side. `normalize_and_return_hostname` lowercases
  whatever FQDN the client put in `user_values_json` and validates it; the client composes
  it. So moving the scheme is a change to the validators and the two clients, not to
  derivation, charts, or product schemas.
- The `subdomain` column already exists, added by `per-user-tls-certificates` along with its
  index and migration, and is what the account's DNS record and TLS certificate are derived
  from. That change already issues `*.<subdomain>.<domain>` and refuses to reconcile a
  deployment whose owner holds none, so the certificate covering `<app>.<subdomain>.<domain>`
  is in place before this change produces the first such name.

Interaction design, mockups and a working prototype of the dialog:
<https://claude.ai/code/artifact/359c879f-7851-47a2-b869-dc25448cc756>

## Goals / Non-Goals

**Goals:**

- Every account that can deploy holds one permanent label, chosen by its owner.
- The choice is made once, understood when it is made, and cannot be silently undone.
- Every application is addressed beneath its owner's label, and beneath nobody else's.

**Non-Goals:**

- Migrating existing deployments, and assigning subdomains to existing accounts. Both are
  operator work, done as part of the rollout rather than by this change.
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

### D5: The two namespaces are separated by depth, not by a collision rule

Under a configured wildcard domain, **one label is a subdomain and two labels are an
application**. `alice.freepod.eu` is an account; `photos.alice.freepod.eu` is one of its
apps. The two can never collide, because nothing is ever addressed at both depths.

An earlier draft of this change shipped the claim alone and kept flat deployment hostnames,
which put subdomains and applications at the same depth and therefore needed a rule
refusing `alice.freepod.eu` as a deployment hostname while `alice` was somebody's
subdomain. That rule was a consequence of the seam, not of the design: it exists only in the
interim state, it has to be explained in three places, and it makes the checker answer a
question the finished system never asks. Moving the scheme in the same change deletes both
the rule and the interim.

The cost is that this change is larger and cannot be rolled out piecemeal. That is
acceptable here because it is not rolled out piecemeal either way — the whole per-account
addressing program lands on one branch, is exercised on dev, and reaches production in a
single step that also assigns subdomains to existing accounts and moves their deployments
beneath them.

### D6: The odometer rests on a placeholder, and stops

The animation exists to make one thing legible in a second: the left-hand slot is a space
the user is being given, not a field they must fill. Two constraints follow, and both were
found by watching it rather than by reasoning:

- **It must not rest on a real name.** Coming to rest on `wiki` asserts that the user picked
  it and that it is theirs. The home slot reads `your app`, set in the UI face and italic
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

### D9: The hostname check endpoint becomes authenticated

`GET /api/hostnames/{fqdn}` has been public since it was written, on the reasoning that its
answer carries nothing sensitive. Under D5 it answers two different questions depending on
depth, and the deployment-side one now depends on who is asking: whether
`photos.alice.freepod.eu` is usable is a different answer for Alice than for Bob.

No anonymous caller is lost. The endpoint is reached from exactly one place — `HostnameField`
inside the deploy dialog — plus the claim dialog and the CLI, all of which are authenticated
already; the landing page never calls it. Requiring authentication also closes the
DNS-amplification handle the endpoint's own comment documents as an accepted risk, since
`_check_cname` resolves caller-controlled nameservers.

The consequence is that `account-subdomain-record`'s "availability is answerable without
authentication" requirement is withdrawn. Its rationale — signing up is free, so
authenticating stops nobody, and claimed subdomains are public in certificate transparency
logs anyway — remains true; it is simply no longer worth the split answer.

### D10: Ownership is enforced where the owner is known

A deployment hostname under a wildcard domain must sit beneath its own owner's subdomain.
The check needs the owning user, so it lives in `create_deployment` beside the other two
preconditions rather than inside `require_valid_hostname_for_deployment`, which is called
with a session and an FQDN and has no notion of an owner.

It runs before the hostname checks rather than beside the Terms of Service one, because it
is what makes the ownership check answerable: an account holding no subdomain compared
against a name under somebody else's would be refused as `claimed`, a conflict with nobody.
The consequence is that an account that has settled neither precondition is told about the
subdomain first.

The endpoint answers what it can: whether the application label is free beneath the
subdomain it was given. Under D9 it knows the caller, so it can and does refuse another
account's namespace — but the authoritative refusal is the one at create, because that is
the path a client cannot skip. This is the same shape as the ToS precondition: the client is
told early as a courtesy and the server enforces it regardless.

### D12: The dashboard renders the picker inline; only the deploy path uses a modal

An earlier build put a card on the dashboard whose only action was to open the modal, and
hid the rest of the dashboard behind it. Both halves were wrong.

The card carried nothing the picker does not: it repeated the same heading and lede, its
static preview was a worse version of the reel, and it put the odometer — the one device
that explains what the left-hand slot is — behind a click. Auto-opening the modal instead
was rejected for a different reason: a modal is a response to an action, and one that opens
by itself dims an empty page, steals focus on load, and turns Escape into an accidental
answer to a permanent question.

Hiding the dashboard was the worse half. An account can hold deployments and no subdomain
at once — every existing account is in that state until the rollout — so the takeover would
have greeted them with their running applications replaced by a name picker.

So the dashboard renders the picker inline above its own content, and the modal survives
only where the user acted and expects to be returned: the deploy path. One component, two
containers.

The odometer belongs to only one of them. It answers "what goes in front of my address?",
which is a live question on the deploy path and a premature one on the dashboard, where the
user has chosen no application and is being asked for the account's own name. Dropping it
there also stops the field needing three columns, which is what made it sprawl across a wide
screen; the address is capped at a readable measure in both containers regardless.

### D11: The wildcard domains endpoint is deleted, not just unused

`GET /api/domains` existed so a client could offer a choice of wildcard domain to
put an application under. Under D5 there is no such choice: an account is addressed
beneath one name, its own, and `GET /api/me/subdomain` reports it.

Leaving it in place as a harmless read was considered and rejected. Its answer is
actively wrong to act on — a client that reads `["freepod.eu"]` and completes a bare
label to `photos.freepod.eu` produces exactly the depth the validator now refuses.
An endpoint that invites the one composition the platform rejects is worse than an
absent one. Both consumers are in this change, and the platform has no third client.

`settings.wildcard_domains` stays: it is what tells the two namespaces apart
server-side. `GET /api/cname-target` stays too, because custom domains are unchanged
and still need a target to point at.

## Risks / Trade-offs

- **The change is large and lands as one unit.** Accepted per D5: the alternative is a seam
  whose only artifact is a rule the finished system deletes.
- **Every released `freepod` client breaks against the new scheme.** A bare
  `hostname: photos` completes to `photos.freepod.eu`, and a project already
  pointing at one is the same shape; both are now refused as `invalid`, with an
  error that does not explain why. Accepted deliberately: the client has no users
  yet, so this is the cheapest moment it will ever be. No version floor or
  targeted refusal is built.
- **The prefill nudges people toward their own name, which reaches certificate transparency
  logs permanently** once they deploy. Accepted deliberately in favor of the shortest path
  for a general audience; mitigated only by the dialog stating that the address is public.
- **Permanence with no escape hatch means support tickets** about typos and regretted names,
  answered by an operator editing the database or by nothing. Accepted: every mechanism for
  changing one is a mechanism for breaking somebody's addresses, and the alternative
  interacts badly with certificates, links and federated applications.
- **Existing accounts hold no subdomain, and existing deployments sit at the old depth.**
  Both are settled by hand in the same rollout, so the preconditions never meet an account
  or a deployment in the old shape. Nothing here needs to tolerate that state.
- **A claim races another claim.** Two users can be told the same label is available and both
  submit. → The unique index decides; the loser gets a refusal and the dialog stays open with
  the name marked taken. The check is advisory by nature and cannot be made otherwise.

## Migration Plan

1. Schema and API first: the column, its index, the claim and read endpoints. Inert on their
   own — nothing calls them, and no user-visible behavior changes.
2. The hostname checker's depth dispatch, its authentication, and the ownership rule at
   create. From here a deployment must be addressed at the new depth, so dev is migrated at
   this point: subdomains assigned to the two accounts that exist, and their deployments'
   hostnames moved beneath them.
3. The UI and the CLI: the claim dialog, the first-run dashboard state, the settings panel,
   `HostnameField`'s new shape, and the client's hostname completion and refusal.
4. Production is cut over in one step, which assigns a subdomain to every existing account
   and moves every existing deployment's hostname beneath its owner's. Operator work,
   outside this change.

**Rollback:** before step 4 there is nothing to roll back in production. After it, reverting
means restoring the previous API image and moving the hostnames back — the column and its
claims are additive and stay valid either way.
