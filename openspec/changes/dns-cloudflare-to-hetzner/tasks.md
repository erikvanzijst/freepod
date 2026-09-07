## 1. Preconditions

- [ ] 1.1 Get Hetzner's answer on the per-zone record limit — what 500 can be raised to, and whether it can be raised again as the platform grows — and verify the answer is recorded in the ticket before any other task starts. A fixed low ceiling means this change does not proceed.
- [ ] 1.2 Confirm in writing that creating records for end users is within Hetzner's terms for the DNS product, and verify the answer is unambiguous rather than a general reference to the AUP.
- [ ] 1.3 Export the `freepod.eu` zone from Cloudflare in BIND format, commit it with this change, and verify the export is complete by comparing its record count against the dashboard.
- [ ] 1.4 Identify every consumer of the Cloudflare API token and zone outside this repository — the homelab tfvars share the variable — and verify none will break when the token is revoked.

## 2. DNSSEC

- [ ] 2.1 Determine whether `freepod.eu` is DNSSEC-signed, by querying the registry for a DS record rather than by reading the Cloudflare dashboard, and record the answer.
- [ ] 2.2 If signed: disable signing at Cloudflare, remove the DS record at the registrar, and verify with `dig DS freepod.eu @<registry nameserver>` that none is published.
- [ ] 2.3 Wait out the DS record's TTL and verify a validating resolver returns unsigned answers for the zone before continuing. Nothing in section 4 may start before this passes.

## 3. The Hetzner zone

- [ ] 3.1 Create the Hetzner project and API token, add the `hcloud` provider to `tf/deps/providers.tf`, and verify `terraform init` resolves it.
- [ ] 3.2 Declare the zone and every record from the export as `hcloud_zone` and `hcloud_zone_rrset` resources in a new module under `tf/deps/`, and verify the plan creates exactly the records in the export and nothing else.
- [ ] 3.3 Apply, then query Hetzner's nameservers directly for every name in the export and verify each answer matches Cloudflare's — type, value and TTL.
- [ ] 3.4 Verify MX records individually, if any exist, including that mail continues to be deliverable after cutover.
- [ ] 3.5 Verify CAA records individually: either none exists, or those that do authorize Let's Encrypt.
- [ ] 3.6 Lower TTLs on the Cloudflare zone to a few minutes and verify the previous values have expired from a public resolver before cutover.

## 4. Cutover

- [ ] 4.1 Change the NS records for `freepod.eu` at the registrar and record the time, so the previous NS TTL window is known.
- [ ] 4.2 Verify the apex, `keycloak.freepod.eu`, the Grafana hostname, a live deployment hostname and `dev.freepod.eu` all resolve correctly through Hetzner, querying from a resolver that holds no cached NS records for the zone.
- [ ] 4.3 Verify the SSH edge is reachable by name on both environments (`freepod.eu:22`, `dev.freepod.eu:23`), which resolves through this zone and has no ingress object to notice it.
- [ ] 4.4 Verify an existing deployment still serves valid TLS, confirming the wildcard certificate in Traefik's store is unaffected by the delegation change.

## 5. cert-manager

- [ ] 5.1 Add the `hcloud/cert-manager-webhook-hetzner` Helm release to `tf/deps/certmanager/`, pinned to a version, and verify the webhook pod is running and its APIService is available.
- [ ] 5.2 Replace the Cloudflare token Secret with the Hetzner one and repoint both DNS-01 `ClusterIssuer`s at the webhook solver (`groupName: acme.hetzner.com`, `solverName: hetzner`), verifying both issuers report Ready.
- [ ] 5.3 Force an issuance against the **staging** DNS-01 issuer and verify it completes end to end, confirming that the solver writes challenge records into the zone the ACME server actually queries.
- [ ] 5.4 Force a renewal of the production wildcard certificate and verify the new certificate is browser-trusted and covers `freepod.eu`, `*.freepod.eu` and `*.dev.freepod.eu`.
- [ ] 5.5 Verify the HTTP-01 issuer for custom domains still works, by issuing for a test custom domain — it involves no DNS provider, so this is a regression check rather than a change.

## 6. Cleanup

- [ ] 6.1 Remove `cloudflare_api_token` and the unused `cloudflare_email` from `tf/deps/variables.tf`, `tf/deps/main.tf` and `tf/deps/certmanager/variables.tf`, and verify a plan against a tfvars file without them is clean.
- [ ] 6.2 Update `tf/README.md` and `tf/deps/README.md` where they describe Cloudflare as the DNS-01 provider, and verify no stale reference remains.
- [ ] 6.3 After the previous NS records' TTL has comfortably elapsed and section 1.4's consumers are confirmed clear, delete the Cloudflare zone and revoke its token, and verify resolution is unaffected afterwards.

## 7. Follow-up

- [ ] 7.1 Decide whether to re-enable DNSSEC at Hetzner as its own change, and record the decision either way rather than leaving the zone quietly unsigned after having been signed.
- [ ] 7.2 Add the zone's record count against the provider limit to whatever the platform already watches, so the ceiling is approached visibly rather than discovered by a failed record creation.
