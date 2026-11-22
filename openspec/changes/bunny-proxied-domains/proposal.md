## Why

Freepod now accepts custom domains proxied through Cloudflare (#269), so owners can put a CDN,
DDoS protection and a WAF in front of their apps. Cloudflare is a US provider, which sits
awkwardly with Freepod's European digital-sovereignty message. Bunny.net (BunnyWay d.o.o.,
Ljubljana, Slovenia) offers the same three things — a CDN, network DDoS mitigation and the
Bunny Shield WAF — from an EU company, and should be offered as an equal, and preferably the
recommended, alternative.

This change is scoping: it records how Cloudflare support works, how each piece maps to Bunny,
where Bunny differs, and a design and plan. Two spikes (design D4, D5) must run on the dev
cluster before the specs here are final.

## What Changes

- **A second recognized proxy, `bunny`.** A custom hostname is accepted as proxied through
  Bunny when it is a CNAME to a Bunny pull zone (`*.b-cdn.net`), or — at an apex flattened by
  Bunny DNS — when all its A/AAAA records are Bunny edge addresses. Either way it needs the
  same `_freepod.<fqdn>` ownership TXT record Cloudflare does, and is reported with
  `proxy: "bunny"`. The hostname check's response shape does not change; `proxy` gains a value.
- **Proxies become a small registry** in `api/app/services/hostnames.py` (name, how it is
  recognized, the owner-facing setup note) instead of `CLOUDFLARE` constants, so a third EU
  proxy is a table entry.
- **Bunny's edge addresses are fetched, not hardcoded.** Bunny publishes several hundred
  individual edge IPs that change as PoPs come and go, so they are read from
  `api.bunny.net/system/edgeserverlist` (+ `/ipv6`) and cached, with a last-known-good copy.
- **HTTP-01 challenges are answered on `:443` too.** Bunny forwards
  `/.well-known/acme-challenge/` to an HTTPS origin over HTTPS, where cert-manager's solver
  Ingress (pinned to `web`) is not reachable, so per-app certificates for Bunny-fronted names
  would never issue. The solver Ingress binds both entrypoints.
- **Per-proxy setup notes** in the UI field, the `freepod` CLI and the docs: Bunny needs
  *Forward Host Header* on, WebSockets on for apps that use them, origin
  `https://<cname target>`, and caching that respects the origin.
- **Docs**: a "Through Bunny.net" section beside "Through Cloudflare's proxy" in
  `custom-domain.mdx`, listed first.
- **CLI**: a minor version bump for the new proxy name and its note. Older CLIs keep working
  (they print the Cloudflare wording for any proxy); `MIN_CLIENT_VERSION` does not move.

Out of scope here, proposed as follow-ups in the design: real client IPs behind either proxy
(D6), Freepod-managed Bunny zones as a paid add-on (D8), and moving Freepod's own DNS off
Cloudflare (D9).

## Capabilities

### Modified Capabilities

- `hostname-validation`: recognizes Bunny-proxied names; Bunny's edge list is fetched.
- `hostname-check-endpoint`: `proxy` may be `bunny`.
- `freepod-cert-manager`: the HTTP-01 solver is reachable on `:443` as well as `:80`.
- `hostname-field-ui`: the proxied state and setup link name the proxy in use.

## Impact

- `api/app/services/hostnames.py`, `api/app/api/hostnames.py`, a new edge-list cache
  (in-process TTL cache, or a row refreshed by an existing worker — D3).
- `tf/deps/certmanager/issuers.tf` (solver entrypoints).
- `ui/src/components/HostnameField.tsx`, `ui/docs/apps/managing/custom-domain.mdx`,
  `ui/docs/developers/hostnames-and-custom-domains.md`, `constraints.md`.
- `cli/src/freepod/values.py`, `cli/src/freepod/__init__.py` (version bump).
- Egress from the API to `api.bunny.net` (HTTPS).
