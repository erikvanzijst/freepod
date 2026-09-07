## 1. The platform TLS namespace and store

- [ ] 1.1 Create the `caelus-tls` namespace in Terraform and verify Traefik can read secrets in it without an RBAC change (its ClusterRole already grants `get/list/watch` on secrets cluster-wide).
- [ ] 1.2 Issue the platform wildcard `Certificate` into `caelus-tls` and verify the resulting secret carries `freepod.eu`, `*.freepod.eu` and `*.dev.freepod.eu`.
- [ ] 1.3 Create a platform-owned `TLSStore/default` in `caelus-tls` with that secret as `defaultCertificate` and `certificates: []`, and verify the empty list is present rather than omitted — a JSON-path write into a missing array fails.
- [ ] 1.4 Mark `spec.certificates` as computed/ignored in the Terraform resource so applies do not revert the reconciler's membership, and verify a `terraform apply` after a reconciler write leaves the list intact.
- [ ] 1.5 Remove `tlsStore` from the Traefik chart values and delete the old `kube-system` store, verifying that exactly one store named `default` exists afterwards.
- [ ] 1.6 Verify the apex and an existing `*.freepod.eu` application still serve the wildcard certificate from the new store, by handshake rather than by reading objects.
- [ ] 1.7 Upgrade the Traefik release and verify the store and its contents are untouched.

## 2. DNS adapter

- [ ] 2.1 Define the DNS interface in `api/app/services/dns.py` — ensure a wildcard record for a name, report whether one exists — and verify no provider type appears in its signature.
- [ ] 2.2 Implement the Cloudflare backend behind it, selected by configuration, and verify a unit test exercises the interface against a fake without touching the provider.
- [ ] 2.3 Add the provider credential, zone and record target to `api/app/config.py`, and verify the settings tests cover their absence (an environment with no DNS provider configured must still start).
- [ ] 2.4 Verify creating a record is idempotent: running it twice against a live zone produces one record and no error.

## 3. Per-account DNS record

- [ ] 3.1 Ensure the account's wildcard record in the deployment reconcile, before any certificate work, and verify it is created on an account's first deployment and left alone on subsequent ones.
- [ ] 3.2 Verify no record is created for the account's own bare name, and that the bare name resolves to nothing.
- [ ] 3.3 Verify deleting a deployment — including an account's last — leaves the record in place.
- [ ] 3.4 Record the empty-non-terminal rationale at the point of creation and in the zone's Terraform, and verify it explains why the record is not redundant beside `*.freepod.eu`.
- [ ] 3.5 Verify a DNS provider failure is reported, requests no certificate, and leaves a later reconcile able to retry from the record.

## 4. Per-account certificate

- [ ] 4.1 Add `ensure_account_certificate` to the provisioner, rendering a `Certificate` in `caelus-tls` covering `*.<subdomain>.freepod.eu` and `<subdomain>.freepod.eu` through the DNS-01 ClusterIssuer, with an explicit ECDSA P-256 private key, a stable name and a label identifying it as platform-managed. Verify a repeat call rewrites the same object rather than churning it.
- [ ] 4.2 Call it from the reconcile after the DNS record and before the Helm release, so issuance and installation proceed in parallel, and verify a first deployment produces both.
- [ ] 4.3 Verify an account's second deployment requests no further certificate.
- [ ] 4.4 Verify claiming a subdomain without deploying produces no certificate.
- [ ] 4.5 Verify nothing deletes the certificate when a deployment, or an account's last deployment, is removed.
- [ ] 4.6 Verify a refused issuance fails the deployment with the cause recorded on it, and that the refusal reaches operators rather than resting on the `Certificate` object alone.

## 5. Waiting for readiness

- [ ] 5.1 Add `JobService.defer_job(job, *, delay)` returning the **same** row to `queued` with a future `run_after` and clearing `locked_by`/`locked_at`, and verify it leaves `attempt` untouched (it counts lease expiries) and never trips `uq_open_reconcile_job_per_deployment`.
- [ ] 5.2 Verify a deferred job is not claimable before its `run_after` and is claimed promptly after, exercising the existing `_claimable_clause` gate.
- [ ] 5.3 Defer the reconcile when the account's certificate is not yet Ready, leaving the deployment in `provisioning`, and verify no worker is held and no lease is consumed while waiting.
- [ ] 5.4 Verify the deferred run completes the deployment once the certificate is Ready, and that the store contains it at that point.
- [ ] 5.5 Bound the wait against the job's `created_at` (no new column) and verify that exhausting it fails the deployment through the reconciler's existing error path, with a cause that names the certificate rather than reading as a release failure.
- [ ] 5.6 Verify a certificate issued after a deployment failed waiting is not deleted, and that a subsequent reconcile of that deployment finds it issued and completes without anything being reset by hand.

## 6. Store membership

- [ ] 6.1 Extend `apply_manifest` (or add a sibling) with server-side apply, a field manager, and a `resourceVersion` precondition, and verify a stale version is refused with `the object has been modified`.
- [ ] 6.2 Add a provisioner method listing the platform-managed certificate secrets in `caelus-tls`, and verify it excludes certificates that exist but have not been issued.
- [ ] 6.3 Implement the reconcile: read the store, compute the desired list from those secrets, and apply `spec.certificates` alone with the version read — retrying from a fresh read on conflict, bounded. Verify no write is made when the list already matches.
- [ ] 6.4 Verify `--force-conflicts` is never passed, and that `defaultCertificate` is absent from every payload the reconciler sends.
- [ ] 6.5 Verify concurrent additions both survive: two workers adding certificates for different accounts at the same time leave both in the list.
- [ ] 6.6 Verify convergence: remove an entry by hand, reconcile an unrelated deployment, and confirm the list is corrected.

## 7. End-to-end

- [ ] 7.1 Verify by handshake that a name under an account's subdomain is served that account's certificate rather than the default wildcard, with no route defined for it — the complete proof that the store reaches routes that never reference it.
- [ ] 7.2 Verify a `*.freepod.eu` application and a custom-domain application are both still served exactly as before, confirming the other two certificate sources are unaffected.
- [ ] 7.3 Verify a renewal is invisible: force one and confirm the secret name is unchanged, the store is not rewritten, and the new certificate is served without a restart.
- [ ] 7.4 Verify an issued account certificate carries an ECDSA P-256 key and that its secret is materially smaller than an RSA one, confirming both scaling assumptions in one check.

## 8. Documentation

- [ ] 8.1 Document the three sources of Traefik's certificate store, and which of them serves what, in `tf/README.md` or `api/README.md`, and verify the account path is described as store membership rather than as anything copied.
- [ ] 8.2 Note in the deployment reconcile documentation that an account certificate is a precondition for its deployments, that the reconcile defers while waiting and fails when the budget is exhausted, and that this is deliberately the terminal behaviour rather than one to revisit when hostnames move.
