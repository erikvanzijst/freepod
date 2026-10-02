---
sidebar_position: 6
title: Variables and secrets
---

# Variables and secrets

Variables configure the running application. They are set per deployment with `freepod var` and are passed to the container as environment variables. A deployment must exist before variables can be set; run `freepod deploy` first.

## Setting variables

```bash
freepod var set LOG_LEVEL=debug FEATURE_X=on   # one release for both
freepod var set API_TOKEN --secret             # prompts for the value without echo
freepod var set -f production.env              # KEY=VALUE lines from a file
```

`freepod var set` saves the variables and starts a [release](deployments-and-releases.md) so they take effect. Several variables in one command produce one release.

A bare `KEY` prompts for the value, which keeps it out of shell history. Prefer that, or `-f`, for credentials.

## Secrets

`--secret` makes a variable write-only. Its value is passed to the container but is never returned: `freepod var list` shows the key without a value, and `freepod var get` fails. To change a secret, set it again.

All variable values, secret or not, are encrypted at rest.

## Reading variables

```bash
freepod var list           # all keys and non-secret values
freepod var list --json    # machine-readable
freepod var get LOG_LEVEL  # one value
```

`freepod var list --json` output can be passed back to `freepod var set -f -`. Secrets in it have no value and are left unchanged.

## Removing variables

```bash
freepod var rm LOG_LEVEL FEATURE_X
```

Removing a variable that is not set succeeds and changes nothing.

## Staging changes

`--stage` saves a change without starting a release:

```bash
freepod var set --stage A=1 B=2
freepod var rm --stage C
freepod deploy --no-build      # applies the staged changes in one release
```

The next release of any kind applies staged changes. `--stage` also works while a release is in progress.

## Rules and limits

| | Limit |
| --- | --- |
| Name | Letters, digits and `_`, not starting with a digit, up to 64 characters |
| Value | 8 KiB |
| Variables per deployment | 256 |
| All values together | 128 KiB |

These names are reserved and cannot be set: `PORT`, `BUCKET_NAME`, and names starting with `AWS_`, `S3_`, `CAELUS_` or `RAILPACK_`. `DATABASE_URL` and the `PG*` variables are set by the platform and take precedence over a variable of the same name. See [Runtime contract: Environment](runtime.mdx#environment).

## Build time

Variables are not available during the build. See [Builds: Build-time variables](builds/index.md#build-time-variables).
