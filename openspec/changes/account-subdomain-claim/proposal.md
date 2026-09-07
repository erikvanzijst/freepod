## Why

Freepod is moving from flat deployment hostnames (`myapp.freepod.eu`) to a per-user
namespace (`myapp.alice.freepod.eu`). That move needs every account to hold one permanent
label, and nothing in the platform holds one today: a user is an email address and a row
id, neither of which is a DNS label anyone would want in their URLs.

The label could have been the Keycloak username, since the registration form already
collects one. It is not, for one decisive reason: whether a label is available depends on
the reserved list, on labels other accounts hold, and on the deployments table — none of
which Keycloak can see. Enforcing it there means a custom Java validator with Freepod's API
on the critical path of registration, and a rejection that arrives on form submit with the
password field cleared. Freepod owns the data, so Freepod asks the question.

This change is the claim and nothing else. The hostname scheme, the per-user TLS
certificates and the migration of existing deployments are separate work that this
deliberately does not touch.

## What Changes

- **An account holds at most one subdomain, permanently.** A new nullable column, unique
  among non-deleted users, set once and never changed or released — not on account deletion
  either, because certificate transparency logs make a released label a hazard rather than
  an asset.
- **A claim endpoint and an availability check.** `POST /api/me/subdomain` claims;
  `GET /api/me/subdomain` reports what the account holds. Availability is answered by the
  existing public hostname checker, which already refuses reserved names and needs no
  authentication to say whether a name is free.
- **Deployment creation requires a claimed subdomain**, enforced server-side exactly as ToS
  acceptance is (`deployment-create-contract`), so a direct API or CLI client cannot skip it.
- **A one-time claim dialog in the web UI**, reached from the first-run dashboard and from
  any attempt to deploy without a subdomain. The dialog is the whole of the interaction
  design: an odometer that teaches what the name is for, live validation as the user types,
  and a confirmation step for a decision that cannot be undone. Mockups and a working
  prototype: <https://claude.ai/code/artifact/359c879f-7851-47a2-b869-dc25448cc756>
- **The CLI refuses and points at the browser.** It does not prompt, validate, or claim.
  A second implementation of a one-time screen — with its own permanence warning and
  confirmation — is not worth maintaining for the few users who arrive through the terminal,
  and it cannot carry the part that makes the decision comprehensible.
- **A claimed subdomain is not a deployable hostname.** While flat hostnames still exist,
  `alice.freepod.eu` must not be claimable as a deployment hostname once `alice` is
  somebody's subdomain. This is what lets the change ship before the hostname scheme moves.
- **Reserved labels come from the existing reserved-hostname list**, not a second list. A
  name is refused as a subdomain when `<label>.<wildcard domain>` is already reserved — the
  same names, for the same reason, with nothing to keep in sync.

## Capabilities

### New Capabilities

- `account-subdomain-record`: the subdomain as a user-level fact — its shape, its
  permanence, how it is claimed and read, and what makes a candidate unavailable.
- `account-subdomain-ui`: the claim dialog — where it is reached from, what it shows, how it
  validates, and how it confirms a decision that cannot be reversed.
- `cli-subdomain-claim`: how the client behaves for an account with no subdomain — refuse,
  name the cause, point at the browser, build nothing.

### Modified Capabilities

- `deployment-create-contract`: adds a claimed subdomain to the preconditions for creating a
  deployment, alongside ToS acceptance.
- `hostname-validation`: a label another account holds as its subdomain is refused as a
  deployment hostname, which adds a check to the ordered sequence the capability specifies.

## Impact

- `api/app/models/core.py`: a nullable `subdomain` column on `UserORM` with a partial unique
  index over `lower(subdomain)` where `deleted_at IS NULL`, mirroring `uq_user_active`; one
  Alembic migration.
- `api/app/api/users.py` and `api/app/services/users.py`: the claim and read endpoints,
  beside the ToS acceptance resource they are modeled on.
- `api/app/services/hostnames.py`: the new check and its reason code.
- `api/app/services/deployments.py`: the create precondition, beside the ToS one at the same
  point in the function.
- `ui/`: a new claim dialog component, a first-run dashboard state, and the deploy entry
  point that routes through it.
- `cli/`: the deploy preflight refusal.
- `tf/app/login/main.tf`: the availability route joins `skip_auth_routes` if a new path is
  used rather than the existing hostname checker.
- Not affected: the hostname derivation scheme, TLS certificate issuance, the reconciler,
  and every existing deployment. A claimed subdomain changes no address until the separate
  hostname change lands.
