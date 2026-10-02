---
sidebar_position: 14
title: Limits
---

# Limits

## Platform

- One user per account. There are no teams or shared access.
- No separate environments such as staging or production; create a separate deployment with another hostname instead.
- Web applications only: one HTTP port per deployment, no inbound TCP or UDP.
- One container and one replica per deployment. No worker processes, scheduled jobs or sidecars.
- No persistent disk. PostgreSQL and object storage are the only persistent stores.
- No built-in integration with Git hosts. See [CI deploys](ci-deploys.md).
- `linux/amd64` images only.

## Reference

| Area | Limit | Details |
| --- | --- | --- |
| Hostnames per deployment | 1 | [Hostnames](hostnames-and-custom-domains.md) |
| Custom domains | `CNAME` to `freepod.eu`; domains themselves only with `ALIAS`, `ANAME` or `CNAME` flattening | [Custom domains](hostnames-and-custom-domains.md#custom-domains) |
| Request body upload | 60 seconds | [Runtime contract](runtime.mdx#timeouts-and-size-limits) |
| Health check | `GET /` returns 2xx or 3xx within 5 seconds | [Runtime contract](runtime.mdx#health-check) |
| Release | Passes the health check within 5 minutes | [Deployments and releases](deployments-and-releases.md#failed-releases) |
| Upload for a build | 100 MB, compressed | [Builds](builds/index.md#limits) |
| Build | 1 hour, 2 vCPU, 6 GiB memory | [Builds](builds/index.md#limits) |
| Variables | 256 per deployment, 8 KiB each, 128 KiB total | [Variables and secrets](variables-and-secrets.md#rules-and-limits) |
| PostgreSQL | 100 MiB; 50 connections | [PostgreSQL](storage/postgresql.mdx) |
| Object storage | 1 GiB, 1,000,000 objects; presigned URLs up to 7 days | [Object storage](storage/object-storage.mdx) |
| Logs | 14 days | [Logs and debugging](logs-and-debugging.md) |
