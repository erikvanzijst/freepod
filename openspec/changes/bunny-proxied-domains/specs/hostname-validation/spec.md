## MODIFIED Requirements

### Requirement: DNS check validates hostname points at the platform
The **CNAME target** is the tenant domain, or `settings.domain` where no tenant domain is configured. It is what custom domains are told to point at.

The DNS check MUST accept a custom hostname that reaches the platform in either of two ways: a CNAME record whose target is the CNAME target, or — the only form a domain apex can take, and what CNAME flattening, ALIAS and ANAME records answer with — A/AAAA records on the platform's own addresses. It MUST also accept, as **proxied**, a hostname that reaches a recognized proxy (Cloudflare or Bunny.net) and carries an ownership record (see *A proxied hostname is accepted, unverified, with an ownership record*). It MUST use the `dnspython` library.

To avoid being misled by a recursive resolver's negative cache (a freshly created record would otherwise be masked by a previously cached "no record" answer until its TTL expires), every lookup MUST query the queried name's zone's authoritative nameservers directly when they can be determined, and MAY fall back to the default system resolver only when those nameservers cannot be determined or reached. A negative answer (NXDOMAIN or no records of the type) from an authoritative nameserver is final and MUST NOT be retried through the system resolver.

The check MUST first query the FQDN's CNAME record. When one exists, the FQDN's addresses MUST NOT be consulted. Its target (trailing dot stripped, lowercased) equal to the CNAME target passes directly; a target under a recognized proxy's CNAME suffix (`.b-cdn.net` for Bunny.net) is proxied and the ownership rule decides; any other CNAME is refused, even when the name it leads to shares the platform's addresses.

When the FQDN has no CNAME, the check MUST collect its A and AAAA records and the platform's addresses, which are the A and AAAA records the CNAME target itself resolves to at check time, following any CNAME chain. The platform's addresses MUST NOT be hardcoded, and MUST be read from the CNAME target's authoritative nameservers by the same rule, so the cluster's own resolver cannot substitute a different answer. Addresses MUST be compared as IP addresses, not as text. The check MUST pass directly only when the FQDN has at least one A or AAAA record and **every** one of them is among the platform's addresses. Otherwise, when every one of them is among one recognized proxy's addresses, the hostname is proxied through that proxy and the ownership rule decides. Any other set of addresses — one foreign address, the proxy's beside the platform's, or two proxies' together — refuses the hostname, because the clients — and the certificate authority's HTTP-01 validation — that reach it would not reach the platform. A hostname MAY carry only A records or only AAAA records, and need not carry every address family the platform does.

The check MUST be skipped when `settings.domain` is an empty string, or when the FQDN is under the tenant domain (the platform serves those names from its own static record). Any failure — a CNAME to neither the CNAME target nor a recognized proxy, no records, a foreign address, NXDOMAIN, the platform's own addresses being unresolvable, or a lookup that no server answers — MUST raise `HostnameException(reason="not_resolving")`, except a proxied hostname's missing ownership record, which raises `ownership_unverified`.

#### Scenario: Freshly created record is picked up without waiting for cache expiry
- **WHEN** an earlier check found no record (a recursive resolver would cache that negative answer), the user then creates the correct CNAME or A/AAAA records, and the check runs again
- **THEN** the check queries the zone's authoritative nameservers directly and passes, without waiting for the recursive resolver's negative cache TTL to expire

#### Scenario: Authoritative nameservers unreachable falls back to system resolver
- **WHEN** the FQDN zone's authoritative nameservers cannot be determined or reached (e.g. outbound DNS is restricted)
- **THEN** the check falls back to the default system resolver, and a definitive resolver failure still raises `HostnameException(reason="not_resolving")`

#### Scenario: CNAME points exactly to domain
- **WHEN** the FQDN has a CNAME record whose target equals the CNAME target (e.g. `"freepod.app"`)
- **THEN** the DNS check passes without looking up any addresses

#### Scenario: CNAME points to the platform domain
- **WHEN** the tenant domain is `"freepod.app"`, `settings.domain` is `"freepod.eu"`, and the FQDN has a CNAME record whose target is `"freepod.eu"`
- **THEN** the function raises `HostnameException(reason="not_resolving")`

#### Scenario: CNAME points to a subdomain of domain
- **WHEN** the FQDN has a CNAME record whose target is a subdomain of the CNAME target (e.g. `"x.freepod.app"`), even one resolving to the platform's addresses
- **THEN** the function raises `HostnameException(reason="not_resolving")`

#### Scenario: CNAME points to a different domain
- **WHEN** the FQDN has a CNAME record whose target is not the CNAME target
- **THEN** the function raises `HostnameException(reason="not_resolving")`

#### Scenario: Apex with A records on the platform's addresses
- **WHEN** `example.com` has no CNAME and an A record whose address is one the CNAME target resolves to
- **THEN** the DNS check passes

#### Scenario: Platform domain reached through its own CNAME
- **WHEN** the CNAME target is `"dev.freepod.app"`, itself a CNAME to a name with A records, and the FQDN's A records carry those addresses
- **THEN** the DNS check passes

#### Scenario: IPv4-only hostname on a dual-stack platform
- **WHEN** the FQDN has only A records, all among the platform's addresses, and the platform also has AAAA records
- **THEN** the DNS check passes

#### Scenario: IPv6-only hostname
- **WHEN** the FQDN has only AAAA records, all among the platform's AAAA addresses
- **THEN** the DNS check passes

#### Scenario: A record pointing elsewhere
- **WHEN** the FQDN has no CNAME and an A record whose address is not one of the platform's
- **THEN** the function raises `HostnameException(reason="not_resolving")`

#### Scenario: One foreign address among matching ones
- **WHEN** the FQDN's A/AAAA records include the platform's address and also any address that is not the platform's — including an AAAA record when the platform has none
- **THEN** the function raises `HostnameException(reason="not_resolving")`

#### Scenario: A record proxied by anyone but Cloudflare
- **WHEN** the FQDN sits behind a proxy other than Cloudflare or Bunny.net, so its authoritative A/AAAA records are that proxy's addresses
- **THEN** the function raises `HostnameException(reason="not_resolving")`

#### Scenario: FQDN has no records
- **WHEN** the FQDN has neither a CNAME nor any A or AAAA record
- **THEN** the function raises `HostnameException(reason="not_resolving")`

#### Scenario: FQDN does not exist in DNS
- **WHEN** DNS lookup for the FQDN returns NXDOMAIN
- **THEN** the function raises `HostnameException(reason="not_resolving")`

#### Scenario: Platform addresses cannot be determined
- **WHEN** the FQDN has A records but the CNAME target resolves to no A or AAAA record
- **THEN** the function raises `HostnameException(reason="not_resolving")`

#### Scenario: DNS resolver times out
- **WHEN** a lookup the check needs times out on every server it may ask
- **THEN** the function raises `HostnameException(reason="not_resolving")`

#### Scenario: DNS check skipped when domain is empty
- **WHEN** `require_valid_hostname_for_deployment` is called and `settings.domain` is an empty string
- **THEN** the DNS check is skipped and the hostname passes that check

#### Scenario: DNS check skipped for wildcard subdomain
- **WHEN** the FQDN is under the tenant domain (e.g. `"photos-alice.freepod.app"` with tenant domain `"freepod.app"`)
- **THEN** the DNS check is skipped and the hostname passes that check

#### Scenario: CNAME to a Bunny pull zone
- **WHEN** the FQDN has a CNAME to `myzone.b-cdn.net`
- **THEN** the FQDN is proxied through `bunny` and the ownership rule decides

#### Scenario: Cloudflare and Bunny addresses together
- **WHEN** the FQDN's A/AAAA records include a Cloudflare address and a Bunny edge address
- **THEN** the function raises `HostnameException(reason="not_resolving")`

### Requirement: A proxied hostname is accepted, unverified, with an ownership record

A proxy answers a proxied record with its own addresses or name, so DNS can neither show
that the name reaches the platform nor that the person claiming it controls it. The
**recognized proxies** are:

- `cloudflare`: addresses are the IPv4 and IPv6 ranges Cloudflare publishes at
  `https://www.cloudflare.com/ips/`, held in the service; no CNAME suffix.
- `bunny`: CNAME suffix `.b-cdn.net`; addresses are the edge servers Bunny.net publishes at
  `https://api.bunny.net/system/edgeserverlist` and `/ipv6`, fetched by the service and cached
  for up to 24 hours. When the list cannot be fetched the last fetched copy MUST be used, and
  with none, no address is Bunny's.

No other proxy is recognized.

When a custom FQDN is proxied (see *DNS check validates hostname points at the platform*), the
check MUST require its **ownership
record**: a TXT record at `_freepod.<fqdn>` whose value is `<handle>.<CNAME target>`, with
the owner's handle (for example `alice.freepod.app`, or `alice.dev.freepod.app` where the
CNAME target is `dev.freepod.app`). The record MUST be read like every other lookup, from the
FQDN's authoritative nameservers. One TXT record at that name whose text — its strings
concatenated, surrounding whitespace and a trailing dot removed — equals the value
case-insensitively MUST satisfy it; other TXT records beside it are ignored. With it, the
hostname is accepted as proxied through that proxy. Without it, or for an owner holding no
handle, the check MUST raise `HostnameException(reason="ownership_unverified")` carrying the
proxy's name.

An accepted proxied hostname is **unverified**: where Cloudflare forwards it cannot be seen,
and the platform does not try. The ownership record is checked wherever the DNS check runs,
so removing it refuses the hostname's next release.

#### Scenario: Proxied and owned
- **WHEN** `photos.example.com` has only A/AAAA records in Cloudflare's ranges, the owner holds `alice`, the CNAME target is `freepod.app`, and `_freepod.photos.example.com` has a TXT record `alice.freepod.app`
- **THEN** the DNS check passes and reports the proxy `cloudflare`

#### Scenario: Proxied without the ownership record
- **WHEN** a proxied FQDN has no TXT record at `_freepod.<fqdn>`, or none holding the owner's value
- **THEN** the function raises `HostnameException(reason="ownership_unverified")`

#### Scenario: Another account's ownership record
- **WHEN** the ownership record holds `bob.freepod.app` and the owner holds `alice`
- **THEN** the function raises `HostnameException(reason="ownership_unverified")`

#### Scenario: The other environment's ownership record
- **WHEN** the CNAME target is `dev.freepod.app` and the ownership record holds `alice.freepod.app`
- **THEN** the function raises `HostnameException(reason="ownership_unverified")`

#### Scenario: The record is matched loosely
- **WHEN** the ownership record's text is `Alice.Freepod.App.`, or is split into the strings `alice.` and `freepod.app`, or sits beside other TXT records at that name
- **THEN** it satisfies the check

#### Scenario: An owner without a handle
- **WHEN** a proxied FQDN is checked for an owner holding no handle
- **THEN** the function raises `HostnameException(reason="ownership_unverified")`

#### Scenario: Cloudflare beside other addresses
- **WHEN** the FQDN's records include a Cloudflare address and any address outside Cloudflare's ranges, including the platform's
- **THEN** the function raises `HostnameException(reason="not_resolving")` whatever TXT records exist

#### Scenario: A CNAME elsewhere is not rescued
- **WHEN** the FQDN has a CNAME to a name other than the CNAME target or a Bunny pull zone, such as `photos.example.com.cdn.cloudflare.net`, and an ownership record
- **THEN** the function raises `HostnameException(reason="not_resolving")`

#### Scenario: Direct records need no ownership record
- **WHEN** the FQDN's records point at the platform directly, by CNAME or by the platform's addresses
- **THEN** no TXT record is looked up, and the verdict carries no proxy

#### Scenario: A Bunny pull zone, owned
- **WHEN** `photos.example.com` has a CNAME to `myzone.b-cdn.net`, the owner holds `alice`, the CNAME target is `freepod.app`, and `_freepod.photos.example.com` has a TXT record `alice.freepod.app`
- **THEN** the DNS check passes and reports the proxy `bunny`

#### Scenario: A Bunny-flattened apex
- **WHEN** `example.com` has only A/AAAA records among Bunny's edge addresses and its ownership record
- **THEN** the DNS check passes and reports the proxy `bunny`

#### Scenario: Bunny's list is unavailable
- **WHEN** Bunny's edge list has never been fetched and cannot be, and `example.com` has only A/AAAA records on Bunny edge servers
- **THEN** the function raises `HostnameException(reason="not_resolving")`, while a CNAME to `*.b-cdn.net` is still accepted with its ownership record
