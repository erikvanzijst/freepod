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

This change carries the claim **and** the hostname scheme it exists for. The two were
planned separately and merged back together once it became clear the seam between them was
pure cost: a claim without the scheme leaves the platform answering hostname questions at a
depth nothing deploys to, and needs a collision rule between subdomains and flat hostnames
that the finished system does not need at all.

## What Changes

- **An account holds at most one subdomain, permanently.** A new nullable column, unique
  among non-deleted users, set once and never changed or released — not on account deletion
  either, because certificate transparency logs make a released label a hazard rather than
  an asset.
- **A claim endpoint and an availability check.** `POST /api/me/subdomain` claims;
  `GET /api/me/subdomain` reports what the account holds. Availability is answered by the
  existing hostname checker, which learns to read a single label under a wildcard domain as
  a subdomain question rather than a deployment question.
- **Deployment hostnames move under the owner's subdomain.** `<app>.<subdomain>.<domain>`
  replaces `<app>.<domain>`. The wildcard depth rule inverts: two labels under a configured
  wildcard domain become the normal shape, one label becomes a subdomain, and
  `nested_subdomain` retires.
- **A deployment hostname must sit under its own owner's subdomain.** Alice cannot deploy
  to `photos.bob.freepod.eu`. Enforced in `create_deployment`, where the owner is known.
- **The hostname check endpoint becomes authenticated.** It now answers a question whose
  correct answer depends on who is asking, and no anonymous caller exists.
- **Deployment creation requires a claimed subdomain**, enforced server-side exactly as ToS
  acceptance is, and distinguished from it by a stable error `code` rather than by its prose.
- **A one-time claim dialog in the web UI**, reached from the first-run dashboard and from
  any attempt to deploy without a subdomain. The dialog is the whole of the interaction
  design: an odometer that teaches what the name is for, live validation as the user types,
  and a confirmation step for a decision that cannot be undone. Mockups and a working
  prototype: <https://claude.ai/code/artifact/359c879f-7851-47a2-b869-dc25448cc756>
- **The deploy dialog's hostname field loses its wildcard dropdown.** There is one Freepod
  address now — the user's own — so the field takes an application label and renders the
  rest. The custom-domain mode is untouched.
- **The CLI refuses and points at the browser.** It does not prompt, validate, or claim.
  A second implementation of a one-time screen — with its own permanence warning and
  confirmation — is not worth maintaining for the few users who arrive through the terminal,
  and it cannot carry the part that makes the decision comprehensible.
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
  deployment, alongside ToS acceptance, and adds the rule that a deployment hostname under a
  wildcard domain must sit beneath its own owner's subdomain.
- `hostname-validation`: the wildcard depth rule inverts, `nested_subdomain` retires, and a
  single label under a wildcard domain becomes a subdomain question.
- `hostname-check-endpoint`: authentication becomes required, and the endpoint answers by
  depth.
- `hostname-field-ui`: the wildcard dropdown is replaced by the holder's own address.
- `cli-deploy`: a bare label completes under the account's subdomain rather than under a
  platform wildcard domain.

## Impact

- `api/app/models/core.py`: a nullable `subdomain` column on `UserORM` with a partial unique
  index over `lower(subdomain)` where `deleted_at IS NULL`, mirroring `uq_user_active`; one
  Alembic migration. Already landed by `per-user-tls-certificates`.
- `api/app/api/users.py` and `api/app/services/users.py`: the claim and read endpoints,
  beside the ToS acceptance resource they are modeled on.
- `api/app/services/hostnames.py`: the depth dispatch, the subdomain question, and the
  retirement of `nested_subdomain`.
- `api/app/api/hostnames.py`: authentication, and the depth-aware response.
- `api/app/services/deployments.py`: the create preconditions, beside the ToS one at the
  same point in the function.
- `ui/`: a new claim dialog component, a first-run dashboard state, the deploy entry point
  that routes through it, a read-only address panel in account settings, and
  `HostnameField` losing its dropdown.
- `cli/`: the deploy preflight refusal, and hostname completion under the account's
  subdomain.
- `tf/app/login/main.tf`: `GET /api/hostnames/{fqdn}` leaves `skip_auth_routes`.
- Operator work at rollout, outside this change: assigning a subdomain to every existing
  account, and moving every existing deployment's hostname beneath its owner's.
- Not affected: TLS certificate issuance and the reconciler, which
  `per-user-tls-certificates` already moved to per-account wildcard certificates covering
  exactly the names this change starts producing.
