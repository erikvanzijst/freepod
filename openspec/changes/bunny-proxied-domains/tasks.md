## 1. Spike on dev (design D4, D5)

- [ ] 1.1 Create a Bunny pull zone: origin `https://dev.freepod.app`, Forward Host Header on; add a
      test hostname CNAMEd to `<zone>.b-cdn.net` with its `_freepod.` TXT record.
- [ ] 1.2 Record at Traefik: SNI and `Host` Bunny sends, and whether Bunny accepts the default
      certificate before the per-app one exists; whether origin-certificate verification exists
      and can be required.
- [ ] 1.3 Confirm `/.well-known/acme-challenge/` reaches the solver once it binds `websecure`.
- [ ] 1.4 Confirm Bunny's caching default for responses without `Cache-Control`, and the exact
      option names for the setup note; confirm WebSockets work with the toggle on (Immich).
- [ ] 1.5 Write the findings into design.md and adjust the specs.

## 2. Backend

- [ ] 2.1 Replace `CLOUDFLARE`/`CLOUDFLARE_NETWORKS` with a proxy registry (`cloudflare`, `bunny`)
      in `api/app/services/hostnames.py`.
- [ ] 2.2 CNAME rule: a target under `.b-cdn.net` is proxied through `bunny`.
- [ ] 2.3 Fetch and cache Bunny's IPv4/IPv6 edge lists (24 h, last-good fallback, short timeout);
      allow API egress to `api.bunny.net` if a NetworkPolicy restricts it.
- [ ] 2.4 Tests: CNAME to pull zone, flattened apex, mixed Cloudflare/Bunny, list unavailable,
      unrecognized CNAME still refused; a network test like `test_cloudflare_networks.py` that
      checks Bunny's endpoints parse.

## 3. cert-manager

- [ ] 3.1 `tf/deps/certmanager/issuers.tf`: solver `router.entrypoints: web,websecure` on both
      issuers; check a Cloudflare-proxied and a direct custom domain still issue.

## 4. Clients

- [ ] 4.1 UI `HostnameField`: proxied tooltip and setup link per proxy (Bunny anchor).
- [ ] 4.2 CLI `values.py`: `PROXY_NAMES["bunny"]`, per-proxy `proxy_note` and
      `describe_verdict`; bump the CLI minor version; tests; tag `freepod-vX.Y.0` after merge.

## 5. Docs

- [ ] 5.1 `custom-domain.mdx`: "Through Bunny.net" first, then Cloudflare; troubleshooting
      (Forward Host Header, WebSockets, caching).
- [ ] 5.2 `hostnames-and-custom-domains.md`, `constraints.md`: both proxies.
- [ ] 5.3 Say that apps see the proxy's address, not the visitor's, until D6 lands.
