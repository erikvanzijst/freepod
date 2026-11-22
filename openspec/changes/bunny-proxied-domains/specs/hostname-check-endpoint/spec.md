## MODIFIED Requirements

### Requirement: Hostname check response reports the name, usability, reason and proxy

The response MUST contain exactly five fields: `fqdn` (the completed, lowercased name that
was checked), `usable` (boolean), `reason` (null when usable, otherwise one of
`invalid`, `reserved`, `in_use`, `claimed`, `not_resolving`, `ownership_unverified`),
`proxy` (`cloudflare` or `bunny` when the name is proxied through Cloudflare or Bunny.net, usable or refused for its
ownership record; null otherwise), and `ownership_record` (with `proxy`, the `name` and
`value` of the TXT record the name needs, as `hostname-validation` defines it, null for an
owner holding no handle; null without `proxy`). A usable name with a `proxy` is unverified:
clients MUST present it as accepted but not confirmed to reach the platform. A refusal MUST be
reported in a 200 body, not as an error status.

#### Scenario: Response shape
- **WHEN** the endpoint returns a response
- **THEN** the JSON body contains only the keys `fqdn`, `usable`, `reason`, `proxy` and `ownership_record`

#### Scenario: A direct name has no proxy
- **WHEN** the checked name is a tenant hostname, or a custom domain that points at the platform directly, or is refused for any reason but `ownership_unverified`
- **THEN** `proxy` and `ownership_record` are null

#### Scenario: A Bunny-proxied hostname
- **WHEN** the caller holds `alice` and `photos.example.com` is a CNAME to `myzone.b-cdn.net` with the TXT record `_freepod.photos.example.com` holding `alice.freepod.app`
- **THEN** the endpoint returns HTTP 200 with `usable` true, `proxy` `bunny`, and the same `ownership_record` a Cloudflare-proxied name would get
