## Context

See proposal.md — Why. Four facts about the current state shape the approach.

**The identifier is enforced by nothing.** `deployment.name` and `deployment.namespace` each
carry only a plain btree; the sole unique guarantee is the pair. Confirmed against the live
migrated schema and by test: two active deployments with the same namespace and different
names commit without error.

**The id is already the identity.** `deployment.id` is a uuid4 primary key, immutable, never
reissued, and already recorded in `.freepod.json` and returned on every deployment read. No
new column, constraint, or generator is needed to make it a usable external identifier.

**The namespace is bound to live cluster state.** It names a real Kubernetes namespace,
created by `ensure_namespace` and destroyed by `delete_namespace`. It cannot be rewritten for
an existing deployment without recreating that namespace and everything in it, so any change
to the generation formula applies to new deployments only.

**The edge already translates.** `resolve()` in `ssh-auth/` looks a deployment up by one field
and returns a *different* pair of fields as the upstream target — host
`{name}-ssh.{namespace}.svc`, username `name`. The identifier a client presents and the
account presented to the sidecar are already two separate values passing through one
function, so changing the first disturbs neither the second nor any chart.

## Goals / Non-Goals

**Goals:**
- One identifier that identifies a deployment among all deployments, permanently, without the
  platform having to maintain anything to make it so.
- Remove `LIMIT 1` from the resolver query. It exists to make an ambiguous answer
  deterministic; once the lookup is a primary key it is hiding nothing and should not remain
  as a licence for ambiguity to return.
- Keep the tenant's namespace out of it: nothing about the client-facing identifier is
  rendered into a release, so no deployment is reconciled by this change.
- Constrain `namespace` to the guarantee it was always assumed to have.

**Non-Goals:**
- A short or human-typeable username. See *Decisions*.
- Rewriting existing namespaces. They are immutable; the formula change applies going forward.
- Any transition window. The cutover is hard, by decision.
- Changing the sidecar's login account, the Service name, or the upstream host.

## Decisions

### The username is the deployment id, in full

`d.id = $1::uuid` is a primary-key lookup: at most one row, no tie-break, and the index is
the one the table already has. Nothing has to be generated, constrained, or kept unique,
because the primary key is all three by definition.

The username is a uuid in its canonical form — 36 characters, which is long. It is accepted
in full only, and a prefix is refused.

Abbreviating it the way git abbreviates a SHA looks attractive and is not safe here. Git's
prefix resolution works because git *reports* ambiguity: `short SHA1 is ambiguous`, and you
type more characters. This edge is required to refuse uniformly and disclose nothing
(`ssh-auth-resolver` § *Refusals are uniform and disclose nothing*), so an ambiguous prefix
would come back as `Permission denied (publickey)` — indistinguishable from a wrong key, a
deleted deployment, or a typo. Worse, whether a prefix is ambiguous depends on which *other*
deployments exist: a prefix that works for months could stop working because an unrelated
tenant created a deployment whose id shares those characters, at a moment the user cannot
connect to anything they did and with an error that tells them nothing.

Two smaller costs point the same way. `d.id::text LIKE $1 || '%'` cannot use the primary key,
so every connection would take a sequential scan under the resolver's 2s statement timeout
unless a functional index were added for it. And a prefix match can return several rows, which
reintroduces exactly the "did this return more than one?" question that removing `LIMIT 1` is
meant to settle.

The length is paid in a place that mostly does not care: the username is copied from
`freepod`, from the UI's SFTP panel, or from the credentials endpoint. If it proves
genuinely painful, a short identifier can be added later as its own stored, unique-constrained
column and accepted alongside the id — additive, and with none of the instability above.

*Alternative considered:* keeping the namespace as the username. Rejected: it publishes where
a deployment runs rather than which one it is, making the cluster's layout a compatibility
surface.

### A malformed username is refused before the store is consulted

`resolve()` parses the presented username as a uuid and refuses `unknown_username` on failure.
Left to PostgreSQL, a non-uuid username would raise a cast error, which the resolver reports as
a failure to answer — an operator would read a typo as an outage, and every junk username would
cost a round trip. Parsing first makes it what it is: an unknown username, refused
indistinguishably from every other refusal.

### The unique index on namespace is unconditional, not partial

Every other uniqueness rule on `deployment` is partial on `status <> 'deleted'`
(`uq_hostname_active`, `uq_deployment_active`). This one is not.

Namespace deletion is asynchronous: `delete_namespace` returns and the namespace continues
terminating in the cluster for as long as its contents take to finalize. A partial index would
let a new deployment be created into that name while the old one is still tearing down, and the
loser of that race is whichever object the finalizer removes last. Since the namespace is not
an address anyone holds, there is nothing to be gained from reissuing one, and the unconditional
index costs a single extra index entry per deleted row.

Dev data is clean — 53 rows, 53 distinct namespaces, including deleted ones — so the index
applies without a backfill.

### The migration verifies before it constrains

`CREATE UNIQUE INDEX` on data that violates it fails with a Postgres error naming the index,
not the offending rows. The migration runs an explicit duplicate check first and raises with
the duplicate namespaces listed. Production data is expected to be clean for the same reason
dev is, but a migration that fails at 3am should say which rows to look at.

Both index changes go in one migration: add `uq_deployment_namespace`, drop
`uq_deployment_ns_name_active`. Dropping second means there is no window in which neither
constraint holds. The ORM's `__table_args__` changes in the same commit — the suite migrates
with the real Alembic chain specifically so model/migration drift is a hard failure.

### Collisions are regenerated in a pre-check loop, with the constraint as the backstop

`create_deployment` runs one transaction that also creates a subscription and may reach
Mollie. Retrying the whole transaction on `IntegrityError` would mean unwinding that, so
instead the namespace is settled before the deployment row is built: generate a candidate,
`SELECT 1 FROM deployment WHERE namespace = :ns`, regenerate on a hit, bounded at 5 attempts.
Exhaustion raises rather than degrading.

This is a check-then-act race in principle. The unique index is what closes it: a lost race
becomes an integrity error on insert instead of two deployments in one namespace.

*Alternative considered:* insert-and-retry on `IntegrityError`, catching the specific index.
Correct without the pre-check, but it entangles retry with subscription and payment side
effects for a branch that will never execute.

### The namespace formula carries a product and an owner, and no email domain

`{slugify(product)[:20]}-{slugify(email_local_part)[:10]}-{random9}`, max 20+1+10+1+9 = 41
characters, well inside the 63-character DNS label limit and inside the 253-character budget
for `{name}-ssh.{namespace}.svc`.

The namespace is read by operators — in `kubectl get ns`, in logs, in a support conversation —
and its job there is to answer *what is this and whose is it*. A product segment and an owner
segment answer that; the email domain adds length without adding an answer. The 20-character
product budget matches `generate_deployment_name`'s, so the two identifiers truncate the same
way and a reader comparing them sees the same prefix.

Both segments reuse the existing `_trim_base` fallback, so a segment that slugifies to nothing
becomes `dep` rather than an empty segment or a doubled hyphen.

### The environment is a setting with no consumer yet

`CaelusSettings` gains `environment`, fed by `CAELUS_ENVIRONMENT` from
`tf/app/caelus/configmap.tf`, which passes through `local.environment` — a value Terraform
already computes and already uses as a namespace label one level up. Nothing derives behavior
from it. It is here because per-environment configuration is otherwise expressed only as
individual values (`domain`, `sftp_host`, `sftp_port`, …) from which the environment itself
cannot be recovered, and the next thing that needs the distinction should not have to infer it
from a hostname.

The default is `dev`, not `prod`: whatever eventually reads it, an unconfigured platform
behaving as production is the wrong way to be wrong.

### The resolver returns the release name upstream

One query change: `WHERE d.id = $1::uuid`, and `LIMIT 1` is removed. The selected columns and
the constructed host are unchanged — `d.name || '-ssh.' || d.namespace || '.svc'` and
`username: name` both still come from the same row. The `-ssh` Service naming convention is
shared between the charts and the resolver and is not touched, so `convention_test.go` still
pins the same construction.

## Risks / Trade-offs

**Every existing SSH invocation breaks at cutover** → Accepted, by decision: no transition
window. The failure mode is a bare authentication refusal, because the edge refuses uniformly
and discloses nothing — the user gets `Permission denied (publickey)` with no hint that the
username is the reason. Mitigation is entirely in what the platform *tells* them: the
credentials endpoint, the UI panel, and `freepod` all report the new username immediately, and
the change should be announced before it ships rather than diagnosed afterward.

**The username is long and not memorable** → Accepted, and the reasoning is under *Decisions*.
It is copied rather than typed in every path the client offers. The escape hatch, if one is
ever wanted, is an additional stored short identifier accepted alongside the id — not a prefix
of it.

**A CLI older than the cutover keeps sending `deployment["name"]`** → It stops working, with
the same undiagnosable refusal. The client reads the identifier from the deployment record it
already fetches, so the fix is a CLI release; the requirement that all four commands derive it
the same way is what keeps the failure total rather than partial and confusing.

**Two environments share a Kubernetes cluster, and namespace uniqueness is per-database** →
Each environment has its own `caelus` database, so the unique index constrains that
environment's rows only, while both create namespaces in one cluster. Two environments
generating an identical namespace requires the same product, the same email local part, and the
same 9-character random draw; the residual is accepted rather than designed against, and it
does not touch SSH, where the identifier is a uuid4 primary key. A dedicated cluster per
environment is the real fix and is out of scope.

**Deleted deployments hold their namespaces forever** → Intended, and the cost is that the
`deployment` table can never release a namespace. The row is already retained for billing and
audit; the index adds no row and no growth beyond its own entries.

## Migration Plan

1. Ship the migration (verify duplicates → add `uq_deployment_namespace` → drop
   `uq_deployment_ns_name_active`) with the ORM `__table_args__` change. Safe on its own: it
   constrains data that already satisfies it and changes no behavior.
2. Ship the `environment` setting with the Terraform variable and ConfigMap entry, and the
   generator's formula change. Both are inert for existing deployments: nothing reads the
   setting, and namespaces are immutable.
3. Ship the API change (`username=str(deployment.id)`) and the resolver change together.
   **This is the cutover.** Shipping the API first would report a username the edge refuses;
   shipping the resolver first would leave the API reporting one that no longer works. Both
   are user-visible breakage of the same size, so they go out together.
4. Ship the CLI release. Its call sites already fail after step 3, so this closes the window
   rather than opening one.

**Rollback:** steps 3 and 4 revert cleanly — the resolver query and the reported field go back
to `name`, and nothing persisted has changed. Step 1 reverts by dropping the index and
restoring the partial one. Step 2 does not revert: namespaces generated under the new formula
are already cluster state and stay as they are, which is harmless, since the formula was never
what any lookup depended on.
