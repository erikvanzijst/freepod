---
name: onboard-product
description: Onboard a new third-party application into Freepod as a curated product, from nothing to a reviewed pull request - analyze upstream's packaging, write a standalone Helm chart and catalog file, prove it on the dev cluster, and open the PR. Always run interactively with a human. Not for upgrading an existing product; that is products/UPGRADING/SKILL.md.
---

# Onboard a curated product

Freepod offers curated self-hosted applications that tenants deploy with one
click. Each is a Freepod-owned Helm chart (`products/<slug>/chart/`) plus a
catalog file (`products/catalog/<slug>.yaml`) that the platform reconciles into
its database on rollout. This skill takes one new application from nothing to a
pull request that adds both.

## How this runs

**Always interactively, with a human at the keyboard.** When anything needs
clarification, a judgment call, or a decision the repository doesn't already
answer, stop and ask. Don't assume, and don't pick a default and carry on. The
sibling upgrade skill runs unattended and is written to guess and escalate;
this one has someone to ask, so it asks.

**The deliverable is one pull request.** Not a production deployment, not a
rollout. Merging and shipping are the human's.

**The dev cluster is yours; production is off-limits.** One kubectl context
reaches both namespaces: `caelus-dev` is dev, `caelus` is production. On dev,
do whatever the work needs. Never read from, write to, or deploy into
production, by any means.

## 1. Orient before writing anything

This skill is deliberately thin on specifics. Freepod moves, and per
`AGENTS.md` § Documentation Layering, OpenSpec is the source of truth and
prose points at it. The living artifacts are always current; anything copied
here would not be. Read:

- `AGENTS.md`, for the repo's conventions.
- `products/catalog/catalog.schema.json`, and the specs it implements:
  `openspec/specs/product-catalog-format/` and `catalog-reconciliation/`.
- The most recently onboarded product, end to end: its catalog file, chart,
  README, and every test that names its slug
  (`grep -rl <slug> api/tests ops/upgrader/tests`). Those tests are the
  registrations a new product also needs.
- `openspec/specs/ssh-chart-contract/spec.md`, and the `caelus.*` values an
  existing chart consumes. These are contracts every chart must satisfy.

## 2. Start from upstream's own packaging

Upstream's reference deployment is the starting point: its official Helm chart
if one exists, otherwise its production compose file, plus the runtime stage of
its Dockerfile and its entrypoint scripts. Our chart translates that into
Freepod's shape; it doesn't reinvent the application's deployment. The
compose-to-Kubernetes translation table in `products/UPGRADING/SKILL.md` §5
applies here too.

Deviate only where a platform constraint forces you to, and record each
deviation and its reason for the PR. Confirm which artifact is the real
reference: repositories often carry compose files for contributors that are not
how upstream tells users to deploy.

## 3. Bundle every dependency

A curated product is packaged standalone. Its database, cache, queue, and any
other service it needs ship in its own chart, at the engine and version
upstream requires. The product owns those choices, and upstream may change
either at any time, so the chart must be free to follow.

## 4. Learn the product's identity model

Before designing any tenant-facing input, work out how the application thinks
about people. Is it single-user, multi-user with one shared library, or
multi-tenant with its own admin tier? Who owns the deployment? This decides
what the deploy dialog asks for, and getting it wrong means reworking the
chart, the values schema, and the catalog together.

A multi-user application whose accounts share one library has exactly one
owner per deployment, so the dialog asks for that owner's own credentials,
not for an abstract "admin password."

## 5. Audit what the tenant can change after deploying

A deployment has to be robust: the chart decides how the application is
structured and configured, and the only levers left to the tenant are ones that
don't matter to the deployment's integrity. So investigate the application's
own admin and settings surface, its admin UI and any settings API, as part of
the deployment contract.

Anything the chart sets deliberately is a lever the tenant must not be able to
move out from under the platform: resource and worker settings, mail and SMTP,
storage paths, the external URL, authentication and federation. Prefer
configuration the application treats as authoritative over what its UI stores,
and disable or hide settings where upstream supports it.

Where the application cannot be constrained, the PR says so plainly, in its own
section: which settings, what a tenant could break, and whether upstream offers
any way to lock them.

## 6. Let the image keep its privilege model

The most common instance of §2. Many images start as root and drop privileges
themselves: a supervisor such as s6-overlay as PID 1, `gosu` or `su-exec` in the
entrypoint, a uid and gid taken from environment variables. Imposing
`runAsUser` or dropping capabilities on such an image makes the container fail
to start. Find the image's own mechanism and use it; run as non-root through
the pod's security context only when the image supports that. No static check
catches this. Only a real deployment does.

## 7. Split the values schema three ways

Every setting belongs to exactly one of:

- **The tenant**, through the catalog's `values_schema`: as few fields as the
  product can work with. Titles and descriptions are shown verbatim in the
  deploy dialog, so they are UI copy, not documentation.
- **The catalog**, through `system_values`: the version pin and every
  deliberate configuration choice.
- **The reconciler**, through the injected `caelus.*` values: hostname and TLS,
  plan sizing, and the other platform contracts.

Secrets the tenant chooses go through the sensitive runtime-var markers,
modeled on an existing product that uses them, so they never land in chart
values. Quote version pins that YAML would read as numbers, such as date-style
tags.

## 8. Prove it on the dev cluster

`helm lint`, `helm template`, and unit tests are necessary and catch none of
the interesting faults. Those appear only when a deployment runs: an init
container that needs credentials to probe its dependency, health probes that
must authenticate, a privilege drop that fails at startup, first-boot ordering
between the application and its database. A product isn't done until it has
been deployed on dev and used.

1. **Publish the chart** with `scripts/publish-charts.sh <slug>`. Published
   versions are immutable: bump `Chart.yaml`'s version for every iteration and
   never re-push one. Expect to burn several versions here; that's normal.
2. **Check that the cluster can pull it**, the way the cluster pulls it. Your
   local helm or docker may be authenticated and show a false green, so fetch
   without credentials. A newly created registry package can start out private;
   making it public is a human's action, so stop and ask.
3. **Create the product, template, and plan by hand** on dev with the `caelus`
   CLI inside the dev API pod (`kubectl exec -n caelus-dev deploy/caelus-api
   -c api -- caelus --as-user <email> …`). Use the CLI, never SQL against the
   database. A single free plan is enough.
4. **Deploy it and use it through the browser.** Drive the freshly deployed
   application with Playwright, as a tenant would: sign in with the credentials
   the deploy dialog collected, and exercise its core features with real data,
   such as real photos with EXIF data for a photo library. A running pod
   proves nothing; the application doing its job does. Also exercise the
   platform features the chart wires up, such as the SSH file access session.
5. **Iterate freely.** During onboarding nothing on dev related to the new
   product needs preserving: delete and recreate the deployment, product,
   template, and plan whenever that's simpler, and rename or restructure as you
   like.

## 9. Hand off the pull request

The PR adds the chart, its README, the catalog file and icon, and the test
registrations from §1. The README carries an **Upstream references** section in
the shape the existing ones use: where release notes live, which artifacts are
the reference deployment, and the pitfalls you found. The upgrade skill depends
on that section every night.

The description states:

- whether the product fits the platform, and each deviation from upstream's
  packaging with its reason;
- the tenant-configuration findings from §5, especially anything that could
  not be locked down;
- what was verified on dev, and how;
- any upstream requirement the platform doesn't meet.

Onboarding exercises paths no existing product has, so it tends to surface
platform bugs. Fix those in their own commits with their own tests, and call
them out in the description; don't work around them inside the product.

On merge, the reconciler adopts the hand-made dev product by its name, so keep
the catalog `name` identical to the dev product's. A mismatch makes adoption
miss and leaves a duplicate product on dev.

Before asking for review, check that:

- `caelus catalog lint` passes, as does the test suite for everything touched;
- the chart renders cleanly with the values the reconciler injects;
- the product was deployed on dev and its core features were used in a browser;
- every deviation, unmet requirement, and unconstrained setting is in the
  description.
