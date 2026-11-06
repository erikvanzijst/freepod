# Notes

## 0.4 Vaultwarden 3.5.0 on dev (2026-11-06)

Chart 3.5.0 hand-pushed from the uncommitted `erik/vaultwarden-poststart-invite`
tree (digest `sha256:5ed85d4eb41c22c60f3ea213d791d565a3b421910253bd25ce5b818357aad10d`).
Tested on dev product 6 through forced templates 283 (template 271's system
values, chart 3.5.0) and 284 (283 plus an Argon2-hashed `admin.token`).

- **Fresh install:** reconcile `ready`, no Job in the namespace, container log
  `bootstrap: invited <owner-email>`.
- **Pod deleted:** the new pod logs
  `bootstrap: <owner-email> already invited or registered; nothing to do`.
- **Wrong admin token** (update to 284): the hook logs
  `bootstrap: admin login failed; cannot invite …`, and kubelet reports
  `FailedPostStartHook` and then `CrashLoopBackOff`. Helm revision 2 `failed`
  (Deployment not ready), revision 3 `Rollback to 1`, the old pod is back at
  2/2, and the deployment is `error` with applied template still 283.

Before that, the hook script was also run locally against
`vaultwarden/server:1.37.1` as UID 1000: invited, then 409, a wrong token and
a readiness timeout each exit 1 with a log line. `vaultwarden/server:1.37.5`
(the catalog tag) ships `sh`, `curl`, `mktemp` and `grep`.

Cleanup: the test deployment was deleted, and template 271 is canonical again.
Templates 283 and 284 remain, because curated templates cannot be deleted; neither
is canonical.

Migration Plan step 0 on dev: no Vaultwarden deployments exist on dev, so the
prerequisite query already returns no rows.

## 9.1 Migration Plan step 0 on dev (2026-11-06)

PR #243 merged; CI published chart 3.5.0, and the catalog init of the rolled-out
API created template 286 (product 6), now canonical. Dev still has no Vaultwarden
deployment on an older template, so the prerequisite query returns no rows.

## 9.2 Dev rollout and step 3 checks (2026-11-06)

API and UI images `power-20261106-1`, built from this branch rebased on master
after #243. `tf/app` applied on the dev workspace with `api_image`/`ui_image`
pinned to that tag; the plan held only the two parking configmap keys and the
image pins. Init containers migrated dev to `a4d2e8f1c7b3`. The API pod has
`CAELUS_PARKING_HOST=caelus-api.caelus-dev.svc.cluster.local` and
`CAELUS_PARKING_PORT=8000`.

- **Traefik:** the live arguments include
  `--providers.kubernetesingress.allowEmptyServices=true` and
  `--providers.kubernetesingress.allowExternalNameServices=true`.
- **A public custom app:** a probe every 0.5 s logged
  `200 → 503 parking` on stop (applied 7 s after the request), and on start
  `503 parking → 503 Traefik (no endpoints) → 200`. No 404 at any point. The
  ledger has two rows, each with `started_at` and `ended_at` and no error.
- **A custom app behind Sign in with Freepod:** while stopped, anonymous
  requests get app-auth's 401, since the Ingress middlewares run before the
  parking backend. The rerouted backend and the parking ExternalName were
  confirmed on the objects.
- **Release to a stopped deployment:** `update-deployment` on stopped
  a public app produced release 31 `succeeded`; the power stayed
  stopped/stopped, the workload stayed 0/0 and the host kept serving the
  parking page.
- **Managed fields:** while stopped, `helm` (Apply) is the only manager of
  `spec.replicas`, at 0; after start it is still `helm`, at 1.
- **Vaultwarden (new deployment on template 286):** the first boot logged
  `bootstrap: invited <owner-email>`. Stopped: the workload went to 0/0,
  both Ingresses (`/` and the `/admin` block) moved to the parking Service, and
  `/` served the parking page while `/admin` kept its 403 from the block
  middleware. Started: no Job in the namespace, and the postStart hook logged
  `already invited or registered; nothing to do`.
- **Matrix (new deployment):** stopped, the StatefulSet and the Element
  Deployment went to 0/0, and all four paths of the host (`/`, `/_matrix`,
  `/_tuwunel`, `/.well-known/matrix`) served the parking page. Started: 200 on
  `/_matrix/client/versions`.
- **App Studio:** stopped, the StatefulSet went to 0/0, all three
  paths of the main host moved to the parking Service, and the preview Ingress
  kept `<release>-app`. Both hosts are behind Sign in with Freepod, so
  anonymous requests get app-auth's 401. Started again afterwards.
- **The page names the visitor's host** (`<title><public-app>.dev.freepod.app is
  stopped</title>`), so `Host` arrives through the ExternalName unchanged.
- **Forged headers on a stopped host:**
  `curl -H 'X-Auth-Request-Email: …' https://<public-app>.dev.freepod.app/api/users/me`
  gets the parking 503, and so does the same request with
  `X-Forwarded-For: 127.0.0.1`. A forged `Host: dev.freepod.eu` is routed by
  Traefik to the API's own router and gets its 401.
- **Port-forward:** `kubectl -n caelus-dev port-forward deploy/caelus-api`,
  then `curl localhost:…/api/products` with `Host: <public-app>.dev.freepod.app`,
  reaches the API (the loopback peer is exempt).
