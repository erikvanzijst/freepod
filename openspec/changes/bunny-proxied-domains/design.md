## Context

### What #269 built for Cloudflare

Cloudflare support is **bring-your-own**: the owner runs their own Cloudflare account and
Freepod never talks to Cloudflare's API. The whole feature lives in the hostname check.

| Piece | How #269 does it |
| --- | --- |
| Recognizing the proxy | A custom FQDN with no CNAME whose A/AAAA records are **all** in `CLOUDFLARE_NETWORKS` (22 CIDRs hardcoded from cloudflare.com/ips, kept honest by `test_cloudflare_networks.py`). A CNAME elsewhere (e.g. `*.cdn.cloudflare.net`) is refused. |
| Proving ownership | A proxied name's addresses prove nothing, so it needs TXT `_freepod.<fqdn>` = `<handle>.<cname target>`, read from the zone's authoritative servers, re-checked at every release. Missing → `ownership_unverified`. |
| Origin trust | None. The platform cannot see where Cloudflare forwards, so a proxied name is accepted **unverified** and every client says so. |
| TLS | Owner sets **Full (strict)**, so Cloudflare verifies Freepod's origin cert. Freepod still gets a per-app Let's Encrypt cert over HTTP-01; owner leaves **Always Use HTTPS** off so Cloudflare forwards `:80` challenges to `:80`, where cert-manager's solver Ingress is bound (`entrypoints: web`). |
| Real client IP | Not handled. Traefik trusts PROXY protocol only from the HAProxy edge and has no `forwardedHeaders.trustedIPs`, so apps see a Cloudflare PoP address in `X-Forwarded-For`, and access logs record it as `ClientHost`. |
| API / clients | `HostnameCheck` gained `proxy` (`"cloudflare"` or null) and `ownership_record`. UI shows an amber cloud and Cloudflare-specific helper text; CLI prints a Cloudflare-specific note (`proxy_note`, `describe_verdict`). |
| Docs | "Through Cloudflare's proxy" in `custom-domain.mdx`. |

### How Bunny.net differs

Bunny's model is a **pull zone**: a named CDN configuration with one origin URL and up to 10
custom hostnames. Facts below are from bunny.net/docs (custom-hostname, ssl-setup,
cdn-acceleration, dns/records, request-headers-to-origin, websockets, connectivity, limits,
shield/pricing), read 2026-11-22.

| Concern | Cloudflare (#269) | Bunny.net |
| --- | --- | --- |
| How a name points at it | Orange-cloud record; resolves to Cloudflare anycast IPs | **CNAME to `<zone>.b-cdn.net`**. Bunny says there is no stable anycast IP to put in an A record. Apex: Bunny DNS flattens CNAME and "PZ" records to A/AAAA. |
| "One-click proxy" | Orange cloud | **CDN Acceleration** in Bunny DNS: creates a pull zone and SSL automatically. Requires Bunny nameservers. |
| Edge IPs | ~22 stable CIDRs | Several hundred individual IPs at `api.bunny.net/system/edgeserverlist` and `/ipv6`; "update periodically as the network changes". |
| Edge TLS cert | Cloudflare's own | Free Let's Encrypt per hostname; needs the CNAME in place first. |
| Origin | The record's target | Pull zone **Origin URL**; **Forward Host Header** sends the visitor's hostname. |
| ACME at origin | `:80` forwarded to `:80` when Always Use HTTPS is off | Bunny forwards `/.well-known/acme-challenge/` to the origin — over the origin URL's scheme, so `https://` origins get it on `:443`. |
| Client IP headers | `CF-Connecting-IP`, appended `X-Forwarded-For` | `X-Real-IP` and `X-Forwarded-For`, **one address, visitor's own value discarded**; plus `CDN-RequestCountryCode`, `CDN-RequestId`, `CDN-JA4`, `CDN-Bot` (Shield). No `X-Forwarded-Host`. |
| WebSockets | On by default | **Off by default** per pull zone; toggle on; 500 concurrent by default (up to 25,000 self-serve), billed at $0.235 per million connection-minutes. |
| Timeouts | 100 s to first byte | 10 s connect, 60 s to first byte (configurable). Freepod already caps uploads at 60 s. |
| DDoS / WAF | Free plan includes DDoS; WAF tiers | **Bunny Shield**: Basic, Advanced, Business, Enterprise. All include DDoS and core WAF; higher tiers add custom WAF rules, bot detection, larger ACLs. Prices are on bunny.net/pricing (not verified here). Learning mode on first enable. |
| Caching default | HTML not cached unless told | Pull zones are caches first; dynamic apps need cache expiry set to respect origin (spike D5). |
| Jurisdiction | US | Slovenia (EU). PoPs are global, so traffic is still served from non-EU PoPs to non-EU visitors. |

## Goals / Non-Goals

**Goals**
- An owner with their own Bunny account can put a pull zone (and Shield) in front of any
  Freepod app, with the same safety Cloudflare has: ownership TXT, accepted-but-unverified.
- Bunny is documented first and as the recommended option.
- Adding a further EU proxy later (e.g. Myra, Gcore's EU offering) is a registry entry.

**Non-Goals**
- Freepod calling Bunny's API on the owner's behalf (D8, later).
- Restoring real client IPs (D6, separate change, covers Cloudflare too).
- Verifying where the proxy forwards (impossible from DNS, same as Cloudflare).

## Decisions

### D1. Recognize Bunny by CNAME first, edge IPs second

The normal Bunny setup is `photos.example.com CNAME myzone.b-cdn.net`. Today that is refused
by the "CNAME elsewhere is not rescued" rule. The DNS check becomes:

1. CNAME == CNAME target → direct.
2. CNAME target ends in `.b-cdn.net` → proxy `bunny`, ownership rule decides.
3. Any other CNAME → `not_resolving` (unchanged; `*.cdn.cloudflare.net` stays refused).
4. No CNAME: all addresses the platform's → direct; all Cloudflare's → `cloudflare`; all
   Bunny edge addresses → `bunny` (a Bunny DNS flattened apex or CDN-Accelerated record);
   anything else, including a mix of providers → `not_resolving`.

The CNAME is matched on suffix only; any pull zone counts, because ownership is proved by the
TXT record, not by which zone it is. *Alternative considered:* require the owner to name their
pull zone. Rejected: adds a field and proves nothing the TXT record doesn't.

### D2. A proxy registry instead of Cloudflare constants

```python
@dataclass(frozen=True)
class Proxy:
    name: str                      # "cloudflare" | "bunny" — the API's `proxy` value
    cname_suffixes: tuple[str, ...]  # () for Cloudflare, (".b-cdn.net",) for Bunny
    networks: Callable[[], Collection[IPNetwork]]
```

`HostnameException.proxy`, `HostnameVerdict.proxy` and the endpoint keep their shape. The
ownership record is proxy-agnostic, so `ownership_record()` is unchanged; one TXT record
covers switching from Cloudflare to Bunny.

### D3. Bunny's edge list is fetched and cached

The list is too large and too volatile to hardcode. The API fetches both lists over HTTPS with
a short timeout, caches them in process for 24 h, and on failure keeps serving the last good
copy. A cold start with Bunny unreachable treats the list as empty: CNAME-based names (the
common case) still work, only flattened apexes are refused (`not_resolving`), which fails
safe. A seed copy checked into the repo would remove that gap; recommended only if the spike
shows the endpoint is unreliable. The API needs egress to `api.bunny.net`. A weekly CI test,
like `test_cloudflare_networks.py`, checks the endpoints still parse.

*Alternative:* store the list in the database via an existing worker. Better if several API
replicas each fetching daily ever matters; it doesn't at today's scale.

### D4. Answer HTTP-01 on `:443` as well (spike required)

A pull zone whose origin is `https://freepod.app` forwards `/.well-known/acme-challenge/<t>` to
Freepod over HTTPS. The solver Ingress is pinned to `web`, so the request lands on the app's
`websecure` router and 404s; the per-app certificate never issues. Fix: the solver
`ingressTemplate` gets `router.entrypoints: web,websecure`. The exact-path solver router
out-ranks the app's `/` router on both. Before the certificate exists, Traefik answers the TLS
handshake with the default (platform wildcard) certificate, so the spike must also confirm
whether Bunny verifies the origin certificate on that first request, and what SNI it sends
with Forward Host Header on.

Pointing the origin at `http://` instead is rejected: every request would then hit Freepod's
HTTP→HTTPS redirect, and Bunny→Freepod traffic would be cleartext.

**Spike (dev cluster):** create a pull zone, origin `https://dev.freepod.app`, Forward Host
Header on, a `*.example` test name CNAMEd to it, and observe: SNI and Host at Traefik, whether
the solver is reached, whether Bunny accepts the default certificate before issuance, and
whether origin-certificate verification is configurable.

### D5. What the owner must set in Bunny (spike required)

The setup note (UI tooltip, CLI `proxy_note`, docs) for `bunny`:

- **Origin URL** `https://<cname target>` (e.g. `https://freepod.app`), **Forward Host Header
  on**. Without it Traefik routes by `freepod.app` and the owner gets the platform's page.
- **WebSockets on** for apps that use them (Immich, Mattermost, Nextcloud Talk, Matrix,
  Vaultwarden live sync). This is a paid per-connection-minute feature at Bunny.
- **Cache expiration: respect origin**, and do not "Ignore query string" or strip cookies, so
  dynamic pages and logins are not cached. The spike confirms the exact option names and
  whether the defaults already do this for responses without `Cache-Control`.
- Leave HTTP→HTTPS at the edge to Bunny's "Force SSL" (safe now: ACME passes through, D4).

`proxy_note` becomes per-proxy. Older CLIs print the Cloudflare note for any proxy; that is
wrong advice but harmless, so `MIN_CLIENT_VERSION` stays.

### D6. Real client IPs behind a proxy (follow-up, both providers)

Today neither proxy's visitor IP reaches apps or access logs. Trusting proxy headers per
entrypoint (`forwardedHeaders.trustedIPs` = Cloudflare + Bunny ranges) is unsafe on a shared
platform: **anyone** can create a pull zone pointing at any Freepod hostname, including
another tenant's, and set `X-Forwarded-For` with an edge rule, defeating that app's IP
rate-limits and bans. A safe design trusts the header only on routers whose hostname the
platform knows is proxied (the verdict is already stored per release), via a per-router
middleware that rewrites `X-Forwarded-For` from `X-Real-IP`/`CF-Connecting-IP` only when the
peer is in the proxy's ranges. That is a separate change; until then the docs say apps see the
proxy's address.

### D7. Documentation order

`custom-domain.mdx` gets "Through Bunny.net" before "Through Cloudflare's proxy", and the
intro names Bunny as the EU option. The developer constraints table lists both.

### D8. Later: Freepod-managed Bunny ("Protect this app")

With usage-based billing, Freepod could offer a per-app toggle that creates and manages a
pull zone through Bunny's API (`POST /pullzone`, add hostname, free certificate, Shield tier)
and bills bandwidth and Shield at cost plus margin. Benefits: zero setup for the owner,
origin and cache settings always correct, the platform knows which hostnames are genuinely
behind *its* zones (which makes D6 easy to do safely), and tenant hostnames under
`freepod.app` could be protected too. Costs: a Bunny account and API key in caelus, a
reconciler for zones, usage import from Bunny's statistics API into the ledger, and a
support burden. Worth its own proposal once BYO Bunny has users.

### D9. Later: Freepod's own DNS

Only `freepod.eu` still uses Cloudflare. `freepod.app` is already at deSEC, and its DNS-01
works through `pr0ton11/cert-manager-desec-webhook` (`tf/deps/certmanager/desec.tf`, pinned
by digest). To move `freepod.eu` there, add it to that solver's `dnsZones`, extend the deSEC
token's policy to TXT in `freepod.eu`, and drop the Cloudflare solver and token. There is no new
dependency, and deSEC's write limits (15/min, 300/day per domain) are far above what a
handful of wildcard renewals needs. Bunny DNS would need a second webhook
(`aardbol/cert-manager-webhook-bunny`, the one cert-manager's docs list), which is a new
third-party component in the issuance path, for a zone that has nothing to gain from
Bunny's CDN. Recommended: deSEC. Separate change.

## Risks / Trade-offs

- **Unverified forwarding**, same as Cloudflare: a pull zone can point anywhere. Mitigated by
  the ownership TXT; accepted.
- **`.b-cdn.net` suffix is Bunny's to change.** Low risk; it has been stable for years. The
  registry makes adding a suffix a one-line change.
- **Flattened apex detection depends on a third-party list.** Fails closed (refused, not
  wrongly accepted), and CNAME names are unaffected.
- **Owner misconfiguration** (Forward Host Header off, aggressive caching) shows as "my app is
  broken". The docs troubleshooting list and the proxied tooltip name these first.
- **Caching private pages** is the worst failure: a cached logged-in page served to others.
  The spike must confirm Bunny does not cache responses without `Cache-Control` by default; if
  it does, the docs must make "respect origin" a required step, not advice.

## Rough plan

1. **Spike** (½–1 day, dev): D4 and D5 questions above. Outcome recorded in this design.
2. **Backend** (1 day): proxy registry, CNAME-suffix rule, edge-list fetch and cache, tests.
3. **cert-manager** (small): solver on both entrypoints; verify Cloudflare still issues.
4. **UI + CLI** (½ day): per-proxy note and icon tooltip; CLI minor bump; release tag.
5. **Docs** (½ day): Bunny section with screenshots-free steps, constraints table.
6. **Follow-ups**: D6 real client IP; D8 managed Bunny; D9 platform DNS.

## Open Questions

- Does Bunny verify the origin's certificate, and can that be required? (D4)
- Exact Bunny defaults for caching responses without `Cache-Control`. (D5)
- Should the UI name a recommended Shield tier, or stay neutral?
