[![CI](https://github.com/erikvanzijst/freepod/actions/workflows/ci.yml/badge.svg?branch=master)](https://github.com/erikvanzijst/freepod/actions/workflows/ci.yml)
![](ui/public/og-image.png)

# Freepod

**Your digital life, truly yours.**

[Freepod](https://freepod.eu) runs private, dedicated pods of open-source apps
(your photos, files, chat and passwords), hosted in Europe. No ads, no tracking,
no lock-in.

## For everyone

Pick an app from the catalog and Freepod installs it, gives it its own HTTPS
address under your subdomain (or on your own domain), and keeps it up to date.
Each app is your own copy, with its data kept apart from your other apps and from
everyone else's.

The catalog includes [Immich](https://immich.app),
[Nextcloud](https://nextcloud.com), [PhotoPrism](https://photoprism.app),
[Vaultwarden](https://github.com/dani-garcia/vaultwarden),
[Matrix](https://matrix.org), [Mattermost](https://mattermost.com),
[Lemmy](https://join-lemmy.org) and [BookStack](https://www.bookstackapp.com),
with more on the way.

→ [Get started](https://freepod.eu/docs/apps)

## For developers

Freepod also runs the apps you write yourself. Point the `freepod` client at a
project directory and it builds a container from your source (no Dockerfile
needed) and puts it live on its own hostname. Postgres, object storage and
sign-in are built in, and your coding agent can drive it too.

```bash
uv tool install freepod
freepod login
freepod init
freepod deploy
```

→ [Developer docs](https://freepod.eu/docs/developers)

## Open source

Freepod is itself open source under the [MIT license](LICENSE). This repository
holds the whole platform: the web app, the API, the `freepod` client, the app
catalog and the infrastructure it runs on.

Freepod is in beta. Questions, bugs or ideas: email
[support@freepod.eu](mailto:support@freepod.eu) or
[open an issue](https://github.com/erikvanzijst/freepod/issues).

## Hacking on it

Development happens inside a [devcontainer](https://containers.dev/): `./dev up`
starts it and `./dev sh` opens a shell in it. Freepod deploys with Terraform onto
a Kubernetes cluster (a single k3s node will do; see [tf/](tf/)).

Most of the work in this repo is done with coding agents, so the detailed tour of
the architecture and conventions lives in [AGENTS.md](AGENTS.md).
