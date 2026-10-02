---
title: CI deploys
---

# CI deploys

`freepod deploy` runs in any CI system that can install the client. There is no built-in integration with a Git host; CI deploys use a stored credential.

## Prerequisites

- The project's `.freepod.json` is committed, and its deployment exists. Run the first `freepod deploy` from your machine.
- The Terms of Service have been accepted. `freepod deploy` cannot ask for acceptance without a terminal.

## Credential

`freepod login` stores a credential in `~/.config/freepod/tokens.json`. CI uses a copy of that file. Create a separate credential for CI so it can be revoked on its own:

```bash
XDG_CONFIG_HOME=$(mktemp -d) sh -c 'freepod login --device && cat "$XDG_CONFIG_HOME/freepod/tokens.json"'
```

Store the printed JSON as a secret in the CI system, for example `FREEPOD_TOKENS`.

- The credential has the same access as your account: it can change or delete any of your deployments.
- It stays valid as long as it is used at least once every 30 days.
- Revoke it under **Applications** at [keycloak.freepod.eu/realms/freepod/account](https://keycloak.freepod.eu/realms/freepod/account).

## GitHub Actions

```yaml title=".github/workflows/deploy.yml"
name: Deploy

on:
  push:
    branches: [main]

concurrency: deploy

jobs:
  deploy:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v5

      - name: Install freepod
        run: pipx install freepod

      - name: Restore credential
        env:
          FREEPOD_TOKENS: ${{ secrets.FREEPOD_TOKENS }}
        run: |
          mkdir -p -m 700 ~/.config/freepod
          printf '%s' "$FREEPOD_TOKENS" > ~/.config/freepod/tokens.json
          chmod 600 ~/.config/freepod/tokens.json

      - name: Deploy
        run: freepod deploy
```

`concurrency` keeps two runs from releasing at the same time; a release started while another is in progress fails.

`freepod deploy` prints the deployment's address on stdout and everything else on stderr, and exits non-zero on failure. See [Deployments and releases: Exit codes](deployments-and-releases.md#exit-codes).
