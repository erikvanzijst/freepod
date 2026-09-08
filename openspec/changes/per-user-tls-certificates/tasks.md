## 1. The account subdomain

- [x] 1.1 Add the nullable `subdomain` column to `UserORM` (`api/app/models/core.py`) with a partial unique index over `lower(subdomain)` where `deleted_at IS NULL`, mirroring `uq_user_active`, and verify a second non-deleted row with the same label — in any case — is refused by the database. This is `account-subdomain-claim` 1.1 verbatim; nothing else from that change is implemented here.
- [x] 1.2 Write the Alembic migration and verify `uv run alembic upgrade head` then `downgrade -1` runs clean against the test database.
- [x] 1.3 Reject a deployment whose owner holds no subdomain in `_validate_input_state`, beside the missing-name and missing-namespace checks, and verify the recorded cause names the subdomain rather than reading as a chart or DNS failure.
- [x] 1.4 Seed `erik` and `fred` on dev by hand and verify every dev account that owns a deployment holds a subdomain, because 1.3 fails the reconcile of any that does not. Migration and seed are one step, not two: the column arrives with the image's migration init container, and from that moment every existing deployment fails to reconcile until the seed is in.

## 2. The platform TLS namespace and store

Traefik honours one `TLSStore` named `default` and, unpinned, honours none at all when it finds
two — serving its self-signed certificate to every hostname on the cluster. So the store moves by
moving a pointer, not by creating and deleting objects in a careful order.

- [x] 2.1 Upgrade Traefik from chart 39.0.5/v3.6.10 to 41.5.0/v3.7.13, which is where `defaultTLSResourcesNamespace` exists at all — v3.6 rejects the field and will not start. Migrate the two values the chart renamed on the way (`providers.kubernetesIngressNginx` → `kubernetesIngressNGINX`, `logs.{general,access}` → top-level `log`/`accessLog`), verify the rendered arguments differ from the running ones only where intended, and verify serving, the HSTS middleware and the HTTP→HTTPS redirect afterwards.
- [x] 2.1b Pin `providers.kubernetesCRD.defaultTLSResourcesNamespace` at `kube-system`, where the store already is, and verify the apex still serves the wildcard afterwards and Traefik logs no store ambiguity — this step must change nothing.
- [x] 2.2 Create the `caelus-tls` namespace in Terraform and verify Traefik can read secrets in it without an RBAC change (its ClusterRole already grants `get/list/watch` on secrets cluster-wide).
- [x] 2.3 Issue the platform wildcard `Certificate` into `caelus-tls` and verify the resulting secret carries `freepod.eu`, `*.freepod.eu` and `*.dev.freepod.eu`, and that its serial differs from the `kube-system` one — the difference is what makes 2.6 provable.
- [x] 2.4 Create a platform-owned `TLSStore/default` in `caelus-tls` with that secret as `defaultCertificate` and **no** `certificates` key, and verify Terraform owns only `f:defaultCertificate` in `managedFields` (`kubectl get --show-managed-fields`) — declaring an empty list would claim ownership of the atomic field and make every reconciler apply conflict.
- [x] 2.5 Verify the new store is inert while the pin names another namespace: serving is unchanged and no `Default TLS Stores defined in multiple namespaces` appears.
- [x] 2.6 Flip the pin to `caelus-tls` and verify by handshake that the apex, an existing `*.freepod.eu` application and a custom-domain application are all served correctly, and that the apex's certificate serial is now the `caelus-tls` secret's. This is the cutover; flipping the string back is the rollback.
- [x] 2.7 Set `computed_fields = ["spec.certificates"]` on the Terraform resource so the planner does not report the reconciler's list as drift, and verify a `terraform apply` after a reconciler write leaves the list intact and produces no diff.
- [x] 2.8 Remove `tlsStore` from the Traefik chart values and delete the old `kube-system` store and certificate, verifying that exactly one store named `default` exists afterwards and that serving is unchanged — both are already ignored by the pin, so this step cannot affect it.
- [x] 2.9 Upgrade the Traefik release and verify the store and its contents are untouched.

## 3. DNS adapter

- [x] 3.1 Define the DNS interface in `api/app/services/dns.py` — ensure a wildcard record for a name, report whether one exists — and verify no provider type appears in its signature.
- [x] 3.2 Implement the Cloudflare backend behind it with the official `cloudflare` SDK, selected by configuration, using the server-side name filter (`name={"exact": ...}`) so existence is one query rather than a walk of the zone, and verify a unit test exercises the interface against a fake without touching the provider.
- [x] 3.3 Add the provider credential (`cloudflare_dns_api_token`), the zone id (`cloudflare_dns_zone_id`, an id rather than a name so the token needs no `Zone → Read`) and the record target to `api/app/config.py`, all defaulting to empty, and verify the settings tests cover their absence (an environment with no DNS provider configured must still start).
- [x] 3.4 Verify creating a record is idempotent: running it twice against a live zone produces one record and no error.

## 4. Per-account DNS record

- [x] 4.1 Ensure the account's wildcard record in the deployment reconcile, before any certificate work, as an **unproxied CNAME to the same target the platform's own wildcard names** (D9), and verify it is created on an account's first deployment and left alone on subsequent ones.
- [x] 4.2 Verify no record is created for the account's own bare name.
- [x] 4.3 Verify deleting a deployment — including an account's last — leaves the record in place.
- [x] 4.4 Record the empty-non-terminal rationale at the point of creation, and verify it explains why the record is kept even though on the current provider it *is* redundant: Cloudflare does not apply RFC 4592's rule to empty non-terminals (measured 2026-09-08 with a live challenge record beneath an account's name), so the hazard is latent and arrives with a conformant provider. The zone is not in Terraform until the Hetzner move, so there is nowhere else to record it yet.
- [x] 4.5 Verify a DNS provider failure is reported, requests no certificate, and leaves a later reconcile able to retry from the record.

## 5. Per-account certificate

- [x] 5.1 Add `ensure_account_certificate` to the provisioner, rendering a `Certificate` in `caelus-tls` covering `*.<subdomain>.<domain>` and `<subdomain>.<domain>` through the DNS-01 ClusterIssuer, with an explicit ECDSA P-256 private key and the name `acct-<fqdn with dots replaced by dashes>` (D10), so dev's and production's cannot collide in the one namespace. The platform-managed label goes in `spec.secretTemplate.labels`, not on the `Certificate` — cert-manager does not copy a certificate's own labels onto its secret, and the secret is what 7.2 selects on. Verify a repeat call rewrites the same object rather than churning it.
- [x] 5.2 Call it from the reconcile after the DNS record and before the Helm release, so issuance and installation proceed in parallel, and verify a first deployment produces both.
- [x] 5.3 Verify an account's second deployment requests no further certificate.
- [x] 5.4 Verify claiming a subdomain without deploying produces no certificate.
- [x] 5.5 Verify nothing deletes the certificate when a deployment, or an account's last deployment, is removed.
- [x] 5.6 Verify a *failed request* fails the deployment with the cause recorded on it and nothing installed. A refusal that arrives **after** a successful request — an exhausted allowance, a rejected challenge — is only observable by reading the `Certificate`'s status, which is section 6's wait; the operator-visible half lands there with it.

## 6. Waiting for readiness

- [x] 6.1 Add `JobService.defer_job(job, *, delay)` returning the **same** row to `queued` with a future `run_after` and clearing `locked_by`/`locked_at`, and verify it leaves `attempt` untouched (it counts lease expiries) and never trips `uq_open_reconcile_job_per_deployment`.
- [x] 6.2 Verify a deferred job is not claimable before its `run_after` and is claimed promptly after, exercising the existing `_claimable_clause` gate.
- [x] 6.3 Defer the reconcile when the account's certificate is not yet Ready, leaving the deployment in `provisioning`, and verify no worker is held and no lease is consumed while waiting.
- [x] 6.4 Verify the deferred run completes the deployment once the certificate is Ready. That the store contains it at that point is section 7's, and is verified there — nothing writes the store yet.
- [x] 6.5 Bound the wait against the job's `created_at` (no new column), defaulting to a ten-minute budget and twenty-second deferrals as settings, and verify that exhausting it fails the deployment through the reconciler's existing error path, with a cause that names the certificate rather than reading as a release failure. The cause carries the certificate's name, the budget and whatever cert-manager's Ready condition says — which while issuance is in flight is a generic in-progress message, because a genuine refusal (an exhausted allowance, a rejected challenge) surfaces on the `Order` rather than on the `Certificate`. Reading through to it is worth doing only if these failures turn out to be hard to diagnose in practice.
- [x] 6.6 Verify a certificate issued after a deployment failed waiting is not deleted, and that a subsequent reconcile of that deployment finds it issued and completes without anything being reset by hand.

## 7. Store membership

- [ ] 7.1 Extend `apply_manifest` (or add a sibling) with server-side apply, a field manager, and a `resourceVersion` precondition, and verify a stale version is refused with `the object has been modified`.
- [ ] 7.2 Add a provisioner method listing the platform-managed certificate secrets in `caelus-tls`, and verify it excludes certificates that exist but have not been issued.
- [ ] 7.3 Implement the reconcile: read the store, compute the desired list from those secrets, and apply `spec.certificates` alone with the version read — retrying from a fresh read on conflict, bounded. Verify no write is made when the list already matches.
- [ ] 7.4 Verify `--force-conflicts` is never passed, and that `defaultCertificate` is absent from every payload the reconciler sends.
- [ ] 7.5 Verify concurrent additions both survive: two workers adding certificates for different accounts at the same time leave both in the list.
- [ ] 7.6 Verify convergence: remove an entry by hand, reconcile an unrelated deployment, and confirm the list is corrected.

## 8. End-to-end

- [ ] 8.1 Verify by handshake that a name under an account's subdomain is served that account's certificate rather than the default wildcard, with no route defined for it — the complete proof that the store reaches routes that never reference it.
- [ ] 8.2 Verify a `*.freepod.eu` application and a custom-domain application are both still served exactly as before, confirming the other two certificate sources are unaffected.
- [ ] 8.3 Verify a renewal is invisible: force one and confirm the secret name is unchanged, the store is not rewritten, and the new certificate is served without a restart.
- [x] 8.4 Verify an issued account certificate carries an ECDSA P-256 key and that its secret is materially smaller than an RSA one, confirming both scaling assumptions in one check. Measured: 7.8 KB against the platform wildcard's 10.8 KB — smaller, but a quarter rather than the two thirds the change claimed; the design and spec now carry the measurement.

## 9. Documentation

- [ ] 9.1 Document the three sources of Traefik's certificate store, and which of them serves what, in `tf/README.md` or `api/README.md`, and verify the account path is described as store membership rather than as anything copied.
- [ ] 9.2 Note in the deployment reconcile documentation that an account certificate is a precondition for its deployments, that the reconcile defers while waiting and fails when the budget is exhausted, and that this is deliberately the terminal behaviour rather than one to revisit when hostnames move.
- [ ] 9.3 Note in `tf/README.md` that `caelus-tls`, the store and the platform wildcard are cluster singletons shared by both environments, so a change to them is never dev-only however it was rolled out.

## 10. The synchronous path

- [ ] 10.1 Report a deferred outcome from `caelus reconcile` and exit without polling or sleeping, and verify the deployment is left provisioning with its job untouched — the CLI reconciles in-process with no job row to defer.
