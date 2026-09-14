[![CI](https://github.com/erikvanzijst/freepod/actions/workflows/ci.yml/badge.svg?branch=master)](https://github.com/erikvanzijst/freepod/actions/workflows/ci.yml)

# Freepod

Cloud provisioning tool with FastAPI + SQLModel + Alembic + Typer CLI and React UI.


## Repo layout

This a monorepo with three packages:
- [api/](./api/README.md) -- the FastAPI app
- [ui/](./ui/README.md) -- the React app
- [cli/](./cli/README.md) -- cli for end devs deploying their own projects to freepod 
- [tf/](./tf/README.md) -- the Terraform project to deploy Caelus itself


## Devcontainer
A [devcontainer](https://containers.dev/) is provided for sandboxed development:
- Create the devcontainer: `./dev build`
- Start the devcontainer in the background: `./dev up`
- Open a shell in the devcontainer: `./dev sh`
- Run a command in the devcontainer: `./dev run uv run pytest -s`
- Shut down the devcontainer: `./dev down`

## Deployment

Freepod itself is deployed to kubernetes using the Terraform project in the [tf/](./tf/) directory.


## Kubernetes
Freepod is built to provision application instances into a Kubernetes backend.

The `k8s/` directory contains provisioning utilities and setup instructions for connecting local development workflows to Kubernetes (including generated kubeconfig files).

When using `kubectl` or any other Kubernetes client, always pass the kubeconfig explicitly:
- `--kubeconfig ./k8s/kubeconfigs/<config.yaml>`
