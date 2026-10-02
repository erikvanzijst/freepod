---
title: Hostnames and custom domains
---

# Hostnames and custom domains

Each deployment has exactly one hostname, set as `hostname` in `.freepod.json`. It is either under your subdomain or a domain you own.

## Hostnames under your subdomain

Your account's subdomain, such as `alice.freepod.eu`, is chosen once in the browser. See [Get started](get-started.mdx#3-choose-your-subdomain). Deployments use hostnames one level below it:

```
myapp.alice.freepod.eu
```

- The label (`myapp`) is 1 to 63 characters of letters, digits and hyphens, and does not start or end with a hyphen.
- `freepod init` completes a single label under your subdomain: entering `myapp` sets `myapp.alice.freepod.eu`.
- There is no limit on the number of hostnames under your subdomain, but each deployment has one, and a hostname can be used by only one deployment at a time.
- Hostnames under another account's subdomain, and hostnames more than one level below yours (`a.b.alice.freepod.eu`), are refused.
- Certificates for these hostnames are in place before the first deploy.

## Custom domains

A deployment can use a domain you own: a name within it, such as `app.example.com`, or the domain itself, such as `example.com`.

1. At your DNS provider, point the hostname at Freepod:

   | Hostname | Record |
   | --- | --- |
   | `app.example.com` | `CNAME` to `freepod.eu` |
   | `example.com` | `ALIAS`, `ANAME` or flattened `CNAME` to `freepod.eu`, where the provider offers one. Without one, the domain itself cannot be used. |

   Step-by-step instructions for common providers are in [Custom domain](/apps/managing/custom-domain).

2. Set the hostname in `.freepod.json`, or enter it in `freepod init`:

   ```json title=".freepod.json"
   "user_values": {
     "hostname": "app.example.com"
   }
   ```

3. Run `freepod deploy`.

Freepod checks the record with the domain's authoritative nameservers at every release, and refuses the release if it does not point to Freepod:

- A `CNAME` must point to exactly `freepod.eu`.
- Without a `CNAME`, as with `ALIAS`, `ANAME` and flattened records, every `A` and `AAAA` address of the hostname must be one of `freepod.eu`'s current addresses. Do not create `A` or `AAAA` records with Freepod's addresses by hand: they can change.

It obtains a TLS certificate for the hostname from Let's Encrypt and renews it automatically. Keep the record in place: releases and certificate renewal depend on it.

- Turn off proxying for the record at providers that offer it, such as Cloudflare. A proxied record resolves to the provider's addresses.
- If the domain has `CAA` records, they must allow `letsencrypt.org`.

## Changing the hostname

Edit `hostname` in `.freepod.json` and release:

```bash
freepod deploy --no-build
```

The new hostname serves the deployment once the release completes. The old hostname stops serving immediately and becomes available to other deployments; requests to it are not redirected.

Applications that store their own URL, issue links, or are identified by their hostname, such as federated services, may need their own configuration updated or may not work under a new hostname.
