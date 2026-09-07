## Context

See proposal.md — Why. What shapes the approach:

- The only thing in this repository that talks to Cloudflare is the DNS-01 solver:
  `tf/deps/certmanager/issuers.tf` holds the token Secret and both `ClusterIssuer`s, fed by
  `cloudflare_api_token` from `tf/deps/variables.tf`. `cloudflare_email` is declared but unused,
  documented as parity with the homelab tfvars.
- Traffic does not pass through Cloudflare. The path is the homelab HAProxy to the k3s Traefik,
  so there is no CDN, WAF, proxy or DDoS behavior to reproduce. Nor could there be: Cloudflare's
  free Universal SSL covers one subdomain level, so a proxied `app.user.freepod.eu` would fail
  TLS at their edge regardless.
- The zone's records themselves are not in this repository. They exist only in the Cloudflare
  dashboard, which is why the parity check below has to start from an export rather than from a
  list.
- Hetzner's DNS moved into the Hetzner Cloud API, which brings `hcloud_zone` and
  `hcloud_zone_rrset` into the official Terraform provider, and a first-party cert-manager
  webhook published on `charts.hetzner.cloud`. The older standalone `dns.hetzner.com` API was
  retired in May 2026, and most community cert-manager webhooks still target it.

## Goals / Non-Goals

**Goals:**

- Serve `freepod.eu` from a zone with room for a record per user account.
- Leave the zone reviewable in Terraform rather than hand-entered in a dashboard.
- Cut over without an outage, and keep a fast way back.

**Non-Goals:**

- Any per-user DNS record. This change unblocks that work; it does not begin it.
- Moving the domain's registration. Only the NS delegation changes.
- Re-enabling DNSSEC at the new provider. Disabling it is in scope because the move requires it;
  turning it back on is its own change with its own verification.
- The HTTP-01 issuer for custom domains, which involves no DNS provider at all.

## Decisions

### D1: Hetzner over the alternatives

- **Cloudflare Pro ($20/mo)** buys 3,500 records but is off-mission for an EU-positioned product
  and costs forty times the alternatives.
- **Route 53** is $0.50/month with 10,000 records and a built-in cert-manager solver, and was the
  cheapest option by capability. Rejected on positioning: an EU digital-sovereignty product
  serving its DNS from AWS is a contradiction a user could reasonably point at.
- **deSEC** is free, German, non-profit and automation-native, and is the most on-mission option
  available. Rejected as the platform's only DNS because it is donation-funded and
  volunteer-operated; that is an availability question for the one component whose failure is
  total.
- **Hetzner** is EU-based, already the kind of infrastructure this platform is built on, and is
  the only candidate whose cert-manager webhook and Terraform provider are both first-party. Its
  documented 500 records per zone is lower than Route 53's, but it is explicitly marked as
  increasable on justified demand rather than gated behind a billing tier.

The open question at the time of writing is how far Hetzner will raise 500 and whether it can be
raised repeatedly; a support request is outstanding. A one-time increase and an open door are
materially different propositions, and the answer decides whether this change proceeds.

### D2: The zone is built in Terraform before it is authoritative

Creating the zone at Hetzner does not affect resolution until the delegation moves, so the whole
record set can be declared, applied and verified while Cloudflare is still serving. That turns
the riskiest step of a DNS migration — did every record come across — into a diff two people can
read, and it leaves the zone documented afterwards, which it has never been.

The alternative, importing a zone file through the provider's interface and adopting it into
Terraform later, gets the zone live sooner and leaves the parity check as a manual comparison.
Rejected: the manual comparison is the step that fails.

### D3: DNSSEC comes off first, and it is the one irreversible step

If the zone is signed, the DS record at the registry commits every validating resolver to
rejecting answers that do not verify against it. Move the delegation with that DS in place and
those resolvers return SERVFAIL — not a fallback to unsigned, a refusal — for the DS record's
TTL, whatever is corrected in the meantime.

So: disable signing, remove the DS, wait out its TTL, and only then change the nameservers. This
is the one step in the plan that a rollback does not fix quickly, which is why it comes first and
alone, with its own verification.

If the zone is not signed, this is a no-op — but it must be checked rather than assumed, because
the cost of assuming wrong is the whole platform dark for hours.

### D4: Both providers serve identical answers across the cutover

The delegation change propagates over the parent zone's NS TTL, during which resolvers will use
either provider. Both must be correct for the whole window, which means the Cloudflare zone stays
untouched and any record change during the overlap is made in both.

The Cloudflare zone is retained well past propagation. It is the rollback path, and a rollback is
only fast if what it points back to still answers.

### D5: The solver swap follows the delegation, and is proved immediately

cert-manager writes challenge records into whichever provider its solver is configured for. If
that is not the provider answering for the zone, the ACME server queries a nameserver that never
sees the record.

Nothing surfaces this at the time. The existing wildcard certificate keeps working until it
renews, up to sixty days later, and then fails with no obvious connection to a DNS change made
two months earlier. So the swap is followed immediately by a forced issuance against the staging
issuer, which costs nothing and proves the pairing while the change is still in hand.

### D6: The first-party webhook only

Four community cert-manager webhooks for Hetzner appear in any search, and they target the
`dns.hetzner.com` API that was retired in May 2026. They are the kind of dependency that installs
cleanly, passes a smoke test against a cached response, and fails at the first real renewal.
Hetzner's own webhook is current and is the only one this change will use.

## Risks / Trade-offs

- **DNSSEC handled wrong takes the platform down for hours with no fast fix.** → D3: it is the
  first step, alone, verified before anything else moves.
- **A record is missed in the parity check and one service breaks obscurely.** → The check runs
  from a full export against the new nameservers directly, before cutover and again after, rather
  than from a remembered list. Mail records and CAA deserve individual attention: neither
  announces its absence, and CAA's failure is deferred to the next issuance.
- **The SSH edge is addressed by name.** `freepod.eu:22` and `dev.freepod.eu:23` resolve through
  this zone, so SSH and SFTP go down with a bad cutover alongside HTTP. Easy to forget, because
  it has no ingress object anywhere.
- **Hetzner raises 500 only once.** → Establish the answer before migrating. If the ceiling is
  fixed and low, this change should not proceed and the choice reopens.
- **The Cloudflare token may have other consumers.** The variable is documented as shared with
  homelab tfvars. → Confirm nothing outside this repository uses the token or the zone before
  revoking it, and revoke only after the overlap period ends.
- **Trade-off accepted:** Cloudflare's anycast network is more resilient than what any of the
  alternatives offer, and this move gives that up. For a platform whose users and servers are in
  Europe, and whose ingress is already a single homelab edge, the marginal loss is small — the
  edge is a far weaker link than the DNS was.

## Migration Plan

1. **Settle the record limit.** Hold the rest until Hetzner has answered what 500 can be raised to
   and whether it can be raised again.
2. **Export the Cloudflare zone** in BIND format. This export is the reference for every check
   below and is kept with the change.
3. **Check DNSSEC.** If the zone is signed: disable signing, remove the DS at the registry, wait
   out the DS TTL, verify no DS is published. Nothing else proceeds until this is done.
4. **Lower TTLs** on the Cloudflare records to a few minutes, and let the old values expire, so
   that record-level corrections during cutover take effect quickly.
5. **Declare the zone in Terraform** against Hetzner, from the export. Apply. Query Hetzner's
   nameservers directly for every name in the export and diff the answers. Pay individual
   attention to MX and CAA.
6. **Change the NS records at the registrar.** Both providers now answer identically; resolvers
   using either are correct.
7. **Watch propagation.** Confirm the apex, `keycloak`, Grafana, a deployment hostname, and the
   SSH edge by name, from a resolver known not to be holding cached NS records.
8. **Swap the cert-manager solver**: install the Hetzner webhook, replace the token Secret,
   repoint both `ClusterIssuer`s. Immediately force an issuance against the staging issuer and
   confirm it completes, then confirm the production wildcard renews on demand.
9. **Remove the Cloudflare variables** from `tf/deps`, including the unused `cloudflare_email`.
10. **After the previous NS TTL has comfortably elapsed** — weeks, not days — and only after
    confirming no other system uses it, delete the Cloudflare zone and revoke its token.

**Rollback:** at any point before step 9, restore the previous nameservers at the registrar; the
Cloudflare zone is unchanged and answers correctly. Reverting the Terraform commit restores the
Cloudflare solver. The exception is step 3: DNSSEC, once removed, is re-enabled deliberately at
whichever provider is serving, and is not part of a rollback.
