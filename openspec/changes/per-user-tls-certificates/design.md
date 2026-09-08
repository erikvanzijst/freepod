## Context

See proposal.md — Why. The state that shapes the approach, most of it established by reading
the running dev cluster rather than the code:

- Traefik's `TLSStore` CRD (traefik.io/v1alpha1, chart 39.0.5) carries both a
  `defaultCertificate` and a `certificates` list — "a list of secret names, each secret holding
  a key/certificate pair to add to the store". Neither entry accepts a namespace, so both
  resolve in the store's own namespace.
- The live `TLSStore/default` is in `kube-system`, labelled `app.kubernetes.io/managed-by: Helm`
  and annotated with the `traefik` release, carrying only `defaultCertificate:
  wildcard-freepod-eu-tls`.
- Traefik runs with a bare `--providers.kubernetescrd`: no `namespaces` filter and no
  `defaultTLSResourcesNamespace`, so a store named `default` is discovered wherever it lives.
  Its ClusterRole already grants `get/list/watch` on secrets cluster-wide, so a new namespace
  needs no RBAC change.
- **Two stores named `default` are not a race, they are an outage.** Traefik's documentation says
  it processes "whichever one it encounters"; v3.6.10 does not. It logs `Default TLS Stores
  defined in multiple namespaces` and honours neither, serving `TRAEFIK DEFAULT CERT` for every
  hostname on the cluster. Measured on 2026-09-08 by doing it: 90 seconds of production on a
  self-signed certificate. `providers.kubernetesCRD.defaultTLSResourcesNamespace` is the way out,
  and **Traefik 3.6.10 does not have it** — the field arrived in v3.7, and 3.6 rejects it as an
  unknown field and will not start. So the move requires an ingress-controller upgrade first,
  chart 39.0.5/v3.6.10 to 41.5.0/v3.7.13, which also renamed
  `providers.kubernetesIngressNginx` to `kubernetesIngressNGINX` and `logs.{general,access}` to
  top-level `log`/`accessLog`. Pinned, the ignored store is a warning rather than an error:
  `Ignoring default TLS store: it can only be defined in the "kube-system" namespace`.
- `websecure` is `asDefault: true`, which is why application Ingresses carrying no `tls:` block
  are served over TLS at all — their certificate comes from the store's default.
- Custom domains already work the third way: `custom-user-app-lt697r-ingress` in a tenant
  namespace names `custom-user-app-lt697r-tls`, and Traefik loads it from there.
- `provisioner.apply_manifest()` already writes a manifest to a temp file and runs `kubectl
  apply -f`, which is how the reconciler publishes tenant secrets today.

## Goals / Non-Goals

**Goals:**

- Every account that deploys has a valid certificate for its whole namespace of hostnames,
  reachable by the ingress controller.
- No component holds a copy of certificate material, and nothing has to act on renewal.
- The change is verifiable on its own, before any deployment hostname moves.

**Non-Goals:**

- Deployment hostnames. `_derive_hostname`, `_check_wildcard_depth` and the hostname field keep
  producing and validating single-label names, and `app-tls-injection` is untouched.
- Deployment hostnames, again: the certificate is treated as a precondition for a deployment
  from the start (D7), but no deployment is *addressed* under an account subdomain here.
- Migrating existing accounts or deployments.
- Changing DNS provider, which is its own change.
- Claiming a subdomain. This change needs the *column*, not the interaction: it takes section 1
  of `account-subdomain-claim` — the nullable `subdomain` on `UserORM`, its partial unique index
  and the migration — and leaves that change's claim endpoints, hostname reason code, deployment
  precondition, dialog and CLI refusal untouched. Dev's two accounts are seeded by hand.

An account holding no subdomain is not a case to be lenient about. There is no name to issue
for, so the reconcile fails on it the way it fails on a deployment with no namespace — an
integrity failure naming the subdomain, in `_validate_input_state`. `account-subdomain-claim`
makes that state unreachable from the API by refusing the create; until it lands, the failure is
the only honest outcome and it is not transitional logic anyone has to find and remove later.

## Decisions

### D1: One certificate per account, not per deployment

A certificate per deployment hostname would need almost no new machinery — the reconciler
already issues per-app certificates for custom domains, and it would reuse that path exactly.
It was rejected on two rate limits, the second of which lands on users rather than operators:

- Fifty new certificates per registered domain per week, shared across dev and production. Tied
  to deployments, that ceiling is exhausted by churn: one account creating and deleting
  applications can spend the platform's weekly allowance.
- Five certificates per identical set of names per week. An account iterating on an application —
  deploy, delete, redeploy — loses TLS on the sixth attempt in a week, with a seven-day recovery
  and nothing the platform can do about it.

Per-account certificates track signups, and signups cannot be churned: a subdomain is permanent
and never released, so the count only rises with real accounts. The account's own iteration
becomes free.

### D2: The certificate goes in the store, not on a route

The constraint that shaped the first version of this design — a route's TLS secret must be in
the route's namespace — is real but applies to routes. The certificate store is a separate,
cluster-wide mechanism, and certificate selection happens by server name during the handshake,
before routing. A certificate in the store is therefore served to routes in namespaces that
never reference it.

That is what removes the entire first design: no per-user namespace, no secret copied into every
tenant namespace, no mirroring controller, and no sweep to re-copy after each renewal. The
renewal problem in particular disappears by construction rather than by being solved — a copy
goes stale, a reference does not. The secret name is stable across renewals, so nothing has to
notice one.

Rejected along the way: copying the secret into each tenant namespace with a housekeeping loop
(a sixty-day fuse if the loop ever stops); `kubernetes-reflector` (the same design with the loop
bought instead of built, and a new cluster dependency); and moving routing into a platform
namespace so route and certificate could sit together (workable, but it would take ingress
ownership away from the product charts, and Matrix's three-path routing shows why that variety
belongs in the chart).

### D3: The store moves out of the Helm release

The live store is owned by the Traefik release. A reconciler writing membership into a
chart-rendered object is the shape of the config-revert problem this cluster has already been
bitten by: an unrelated chart upgrade resets it, every account's certificate leaves the store at
once, and the fleet is served the default wildcard for names it does not cover.

Moving the store into `caelus-tls` and out of the release makes ownership explicit. It also has
to move for a plainer reason: `certificates` entries carry no namespace, so the store must live
where the certificate secrets do — which means the platform wildcard's secret moves too.

The move itself is made by pinning `defaultTLSResourcesNamespace`, not by creating and deleting
objects in the right order. Pinned, a store outside that namespace is ignored, so the new store
can be built and inspected while the old one keeps serving; the cutover is then one string, and
it moves only between two states that are both valid. Unpinned there is no such ordering: any
moment in which both stores exist is a moment with no working certificate, which is what makes
"stand the new one up beside the old and verify" — the shape this plan originally had —
unavailable rather than merely slow.

### D4: Field-level ownership, and the declaring side must omit what it does not own

Terraform creates the store with its `defaultCertificate` and **omits `spec.certificates`
entirely**; the reconciler writes only `spec.certificates`, with `kubectl apply --server-side
--field-manager=caelus-tls`.

Omitting rather than initializing is the whole of it, and the distinction is easy to get wrong.
An earlier draft had Terraform declare `certificates: []` so the list would exist. That does not
create an empty list for someone else to fill — it makes Terraform the **owner** of the field.
`certificates` is an atomic list, so ownership is all-or-nothing across the whole list, and
every reconciler apply then fails:

```
error: Apply failed with 1 conflict: conflict with "terraform-sim": .spec.certificates
```

The only way past that conflict is `--force-conflicts`, which this design forbids for exactly
the reason it would then be needed for — a manager that forces its way past ownership can take
`defaultCertificate` too, and drop it on its next write.

Verified on the dev cluster against a throwaway `TLSStore`: with `certificates` omitted from the
declaring side, the reconciler's apply succeeds, a subsequent Terraform apply of its own manifest
leaves the list untouched, and ownership settles as

```
caelus-tls    owns {"f:certificates":{}}
terraform-sim owns {"f:defaultCertificate":{"f:secretName":{}}}
```

Server-side apply creates an absent field on first write, so nothing has to pre-create the list.
It also creates an absent *object*, which is the one thing to guard: an apply of
`spec.certificates` against a missing store would produce a store with no default certificate and
no fallback for connections that match nothing. The reconciler therefore reads the store first —
which it does anyway, for the version precondition in D6 — and refuses rather than creating one.

On the Terraform side, `computed_fields = ["spec.certificates"]` keeps the provider from
reporting the reconciler's list as drift and planning it away. Server-side apply will not prune a
field Terraform never owned, so this is about the planner rather than the API.

### D5: Membership is derived from the cluster, not the database

The question is which certificates can be served; the cluster is authoritative for it. Listing
the secrets in `caelus-tls` gives exactly that set, with no join against deployments, no skew
between a query and reality, and no possibility of naming a secret that has not been issued —
which Traefik logs as an error on every reload.

Deriving it from the users table would be modelling cluster state in Postgres, which is the
opposite of what the reconciler does everywhere else.

### D6: Compare-and-swap, because recomputing the list is not enough

Recomputing the whole list does not make concurrent writes safe — it is the mechanism by which
they are lost. Worker A reads the set, worker B adds a certificate and writes, A writes its
stale list, and B's entry is gone.

The fix is a version precondition. Server-side apply honours `metadata.resourceVersion`,
verified on the dev cluster with a throwaway object: applying with a stale version returns
`Operation cannot be fulfilled ... the object has been modified`, and the same payload with the
current version applies cleanly. So the reconciler reads the store, computes the desired list
from the secrets, and applies with the version it read, retrying from a fresh read on conflict.

This gives compare-and-swap *without* giving up field-level ownership — the payload is still
`spec.certificates` alone, so `defaultCertificate` remains Terraform's.

Two alternatives were rejected. Appending with a JSON patch is atomic and cannot lose an entry,
but accumulates duplicates with no tidy way to remove them. A `caelus sync-tls-store` command
modelled on `sync-network-policies` was proposed and withdrawn: that command is safe because it
is run by hand and never automatically, and an automatic equivalent would need a singleton
writer the platform does not have. With compare-and-swap, convergence is inherent and no such
command is needed.

### D7: The reconcile waits for the certificate, with a budget

Issuance runs in parallel with the Helm install, and usually finishes first: a DNS-01 challenge
is one to three minutes and `helm upgrade --install --wait` has a 300s budget. When it does not,
the reconcile has to wait, and the reason is not politeness about ordering.

Membership is derived from the certificates that exist. A reconcile that completes before
issuance computes a list that does not contain the new certificate, sees no difference from
what is stored, and writes nothing — correctly, by its own rules. Nothing then revisits it: the
next opportunity is the next reconcile of *any* deployment on the platform, which on a quiet
platform may be days away, and for a single-account platform may never come. The account would
hold a valid certificate the ingress controller had never been told about, and the end-to-end
behaviour would be intermittent in a way that depends on unrelated traffic.

So the reconcile defers rather than completing: the deployment stays `provisioning`, the job
returns to the queue with a later `run_after`, and the next run re-checks. The queue already
supports this — `DeploymentReconcileJobORM.run_after` exists and `_claimable_clause` gates queued
jobs on `run_after <= now`. What is missing is a `JobService.defer_job` that returns the *same*
row to `queued` with a future `run_after` and clears `locked_by`/`locked_at`. The same row rather
than a new one, because `uq_open_reconcile_job_per_deployment` permits one open job per
deployment across `(queued, running)` and enqueuing a successor while the current job is still
running raises `DeploymentInProgressException`. It must not touch `attempt`, which counts lease
expiries — how often a worker died holding the job — and would stop meaning that.

Deferring rather than sleeping matters: a sleep inside the reconcile holds a worker process and
burns the job lease, and the lease is what lets a genuinely dead worker's job be reclaimed.

**The wait is bounded**, measured from the job's `created_at` so no new column is needed, and
exhausting the budget fails the deployment through the reconciler's existing error path — the
same path a failed Helm release takes, recording the cause on the deployment. The budget is ten
minutes and each deferral is twenty seconds: a DNS-01 challenge settles in one to three minutes,
so ten tolerates a slow order several times over while still failing inside the window someone
is plausibly still watching their first deployment.

Failing rather than completing is a deliberate choice to build the terminal behaviour now.
Nothing is addressed under an account's own names yet, so a lenient alternative was available:
complete the deployment and let it be served by the default wildcard, as everything is today.
It was rejected because it is a leniency with an expiry date. Someone would have to find it and
reverse it when hostnames move, in a system where the reason for it had been forgotten, and the
failure it conceals — an application published under a name it cannot serve a valid certificate
for — is worse than a deployment that did not complete.

The cost is accepted and worth stating plainly: an exhausted weekly allowance, an issuer outage
or a DNS provider outage now fails the first deployment of any account that does not yet hold a
certificate. Accounts that already hold one are unaffected, since nothing is requested for them.
That is the behaviour these failures should have, and having it from the start means it is
exercised while the blast radius is small.

Nothing is deleted on failure: the `Certificate` remains, cert-manager keeps retrying its order,
and a later reconcile of the deployment finds it issued and completes without anything being
reset by hand.

### D8: Dev issues from production, and shares the allowance

Dev and production both serve names under one registered domain, so their certificates draw on
one weekly allowance. Dev could issue from the staging issuer, which the repository already
defines and which has its own far higher limits, but its certificates are not browser-trusted
and dev is meant to work.

Accepted deliberately, with one consequence worth stating: the allowance is spent by iteration,
not by steady state. Every throwaway account created while developing this feature is a distinct
set of names, so none of them gets the duplicate-certificate exemption, and twenty of them in an
afternoon is a large share of the week — spent against production signups. Worth watching while
this is being built, rather than a reason to change the decision.

### D9: The account's record mirrors the platform's own

`*.freepod.eu` and `*.dev.freepod.eu` are CNAMEs to `kube.freepod.eu`, not address records, and
an account's wildcard is the same: `*.<subdomain>.<domain>` CNAME to the same target. Mirroring
rather than resolving to an address keeps an ingress IP change one edit in one place, however
many accounts exist by then.

The record is created unproxied. A proxied record puts the provider's own edge in front of the
handshake, which terminates TLS somewhere the platform does not control and defeats the store
this change exists to fill.

The provider is reached through its official Python SDK rather than hand-rolled HTTP. Cloudflare
publishes one, its transitive dependencies are already in the API's tree, and it is consistent
with how the payment and object-storage adapters reach their own providers. What it contributes
beyond less code is a server-side name filter, so "does this record exist" is one query rather
than a walk of a zone that grows with the account count. The SDK stays inside the implementation;
the interface it sits behind knows nothing of it.

The zone is identified by id rather than by name. Resolving a name to an id costs a `Zone → Read`
permission on the credential for something that never changes, so the id is configuration and the
token carries `Zone → DNS → Edit` on the one zone and nothing else.

### D10: Names carry the environment, because the namespace does not

`caelus-tls` is one namespace in one cluster, and dev and production both write into it. Their
databases are separate, so `erik` can be a different person in each; the fully qualified names
they resolve to cannot collide, but the object names would.

So a certificate and its secret are named from the fully qualified name they cover, with the dots
replaced: `acct-erik-dev-freepod-eu` beside `acct-erik-freepod-eu`. Every component of that is
already at hand where it is built — the account's subdomain and `settings.domain`, which each
environment's Terraform already sets.

The consequence is that either environment's reconciler derives a membership list containing the
other's certificates, and both write the same store. That is correct rather than tolerated: one
store serves one Traefik, which serves both environments, and the compare-and-swap in D6 is what
already makes two writers safe — it does not care that they are different environments.

## Scaling

Measured against the running cluster: a TLS secret is ~10.8 KB of JSON, the store object is
832 bytes, and each membership entry is ~40 bytes.

- **The store object** reaches Kubernetes' ~1.5 MB ceiling somewhere near 30,000 entries.
  `certificates` is an atomic list, so server-side apply records one ownership entry for it
  however long it gets.
- **Traefik** selects certificates by a map lookup on server name, not a scan. Each
  configuration rebuild re-parses every certificate in the store, but the swap is live — no
  restart, no dropped connections. The only exposure is added latency on TLS handshakes landing
  inside a rebuild, since the certificate store is behind a read/write lock. ECDSA keys are
  specified partly to keep that parse cheap.
- **The reconciler's LIST is the first cost that bites**, because secrets carry key material:
  ~11 MB per reconcile at 1,000 accounts. The remedy, when it is needed and not before, is to
  skip the derivation when the account's entry is already in the store — at the price of no
  longer correcting another account's drift on an unrelated reconcile.

None of these is the binding constraint. The DNS provider's per-zone record limit (500 at
Hetzner, raisable) caps accounts an order of magnitude earlier, and the certificate authority's
50 new certificates per registered domain per week caps growth at roughly 2,600 accounts a year.

## Risks / Trade-offs

- **The account's wildcard DNS record looks redundant beside the platform's.** Anyone tidying
  the zone would remove it, and the applications under it would keep resolving until the next
  certificate renewal wrote a challenge record. → The rationale is a requirement in
  `account-dns-record`, not a comment, and belongs in the zone's own documentation too.
- **One object holds every account's certificate membership.** A bad write affects everyone at
  once. → Derived state makes the content deterministic, compare-and-swap makes concurrent
  writes safe, and the payload is one field. The residual risk is a bug in the derivation, which
  is why the equality check that skips the write in the common case is also the thing that keeps
  a broken derivation from being written continuously.
- **Moving the platform wildcard's secret between namespaces touches the certificate that serves
  everything.** → It is a separate, first step, verified before anything per-account is built.
  The old store and secret stay in place throughout, but they cannot be left *serving* while the
  new one is checked — Traefik honours one default store. What makes the step safe instead is the
  namespace pin: the new store is inert until the pin names it, and because the two secrets are
  different certificates, the handshake's serial number is proof of which store is in effect
  rather than an inference from the objects.
- **The weekly allowance is a real ceiling on signups**, shared with dev, and now a ceiling on
  *first deployments* rather than a quiet limit: an account that cannot get a certificate cannot
  deploy at all (D7). → Fifty new accounts per week is far beyond current growth, and accounts
  that already hold a certificate are unaffected; but if it is ever approached, the request for
  an increase should precede the need by weeks rather than follow a wave of failed first
  deployments.

## Migration Plan

1. Upgrade Traefik to a version that has `defaultTLSResourcesNamespace` (v3.7+), and pin it to
   `kube-system`, where the store already is. Nothing changes; confirm that, including that
   neither the upgrade nor the pin disturbed serving. A Traefik that will not start cannot take
   over — the Deployment is `maxUnavailable: 0` — so a bad upgrade stalls rather than breaking.
2. Create `caelus-tls`, issue the platform wildcard into it, and create the platform-owned
   `TLSStore/default` there with that as its default certificate and no `certificates` key.
   All of it is ignored while the pin names another namespace; confirm serving is unchanged and
   that Traefik reports no ambiguity.
3. Flip the pin to `caelus-tls`. This is the cutover: confirm by handshake that the certificate
   served is the new secret's, identified by serial. Both stores are valid throughout, so there
   is no window, and flipping the string back is the rollback.
4. Remove `tlsStore` from the Traefik chart's values and delete the old store and certificate in
   `kube-system`. Both are already ignored, so this cannot affect serving. Confirm a Traefik
   release upgrade leaves the new store untouched.
5. Add the DNS adapter and the record provisioning, with no certificate work. Confirm a record
   appears for an account that deploys, and that a second deployment changes nothing.
6. Add certificate issuance and store membership. Confirm with a handshake against a name under
   an account's subdomain: the certificate served is the account's, not the default wildcard —
   which is a complete end-to-end proof even though no deployment is addressed there yet.

**Rollback:** each step is independent. Removing an account's certificate from the store returns
its connections to the default wildcard, which is where they are today; the certificates and DNS
records are inert if nothing is addressed at those names. Reverting the move means pointing the
pin back at `kube-system`, which is why step 4 — the one that destroys the ability to do that —
comes after the cutover has been confirmed rather than with it.
