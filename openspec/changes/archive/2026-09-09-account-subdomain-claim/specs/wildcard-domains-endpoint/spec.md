## REMOVED Requirements

### Requirement: Domains endpoint returns Caelus-provided wildcard domains
**Reason**: The question it answers no longer exists. An account is addressed
under one name — its own — so there is no list of wildcard domains for a client
to choose from, and `GET /api/me/subdomain` already reports the only suffix
either client needs. Worse, its answer is now a trap: a client that reads
`["freepod.eu"]` and composes `photos.freepod.eu` produces a name the depth rule
refuses.
**Migration**: The route is deleted from `api/app/api/hostnames.py`. Its two
consumers go with the clients that hold them: `listDomains` and the
`wildcardDomains` prop in the web UI, and `ApiClient.domains` with `_domains`
in `freepod`. `settings.wildcard_domains` is unaffected — it still defines where
the depth rule applies, server-side. `GET /api/cname-target` is unaffected too:
custom domains still need a CNAME target.

### Requirement: Domains endpoint does not require explicit authentication
**Reason**: Removed with the endpoint itself.
**Migration**: `GET=^/api/domains/?$` leaves oauth2-proxy's `skip_auth_routes`
in `tf/app/login/main.tf`, so the edge and the application continue to agree on
which routes are public.
