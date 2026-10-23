# Tasks

## 1. Shared streaming module

- [ ] 1.1 Move the generic half of `api/app/services/deployment_logs.py` (resume parsing, SSE
  helpers, keepalive, `_Cursor`, `fetch_initial`, the follow loop, `StreamLimitExceeded`,
  `stream_registry`) to `api/app/services/log_stream.py`, parameterized by selector, event name and
  a `render(entry) -> dict | None` function (design D2). `deployment_logs.py` keeps target
  resolution, release logic and its selector, and supplies its existing `{ts, line, release}`
  renderer. Verify that the existing pod-log tests pass unchanged apart from import paths.
- [ ] 1.2 Make a line rendered to `None` advance the cursor without emitting. Verify with a unit
  test in which a full batch of unrenderable lines at the cursor neither stalls nor raises
  `cursor_stalled`, and the renderable line after it is delivered once.

## 2. `lookback` on the pod-log endpoint

- [ ] 2.1 Add `lookback` (int seconds, 1..`log_initial_lookback_seconds`) to
  `GET …/deployments/{id}/log` and pass it to `fetch_initial` as a narrower start (design D4).
  Document it in the route's docstring. Verify with API tests: a window returns only lines inside
  it, a window with more lines than the tail returns the newest N oldest-first, an over-retention
  value gets 400 naming the maximum, a non-integer or zero gets 422/400 with no Loki call, and
  `since` takes precedence over `lookback`.

## 3. HTTP log service

- [ ] 3.1 Create `api/app/services/http_logs.py` with the router-prefix selector from design D1. Its
  module docstring should explain the attribution and why it is isolation-safe. Verify with unit
  tests over fixture router names covering multiple hosts, a separately routed path, a
  duplicate-rule hashed suffix, a `@kubernetescrd` router, a sibling deployment in a shared
  namespace, a name that is a prefix of another (`…-ab12cd` vs `…-ab12cd9`), and platform routers
  (`kube-system-…`, `caelus-tenant-apex-…`). Each must match or not match as expected when the
  selector's regex is applied.
- [ ] 3.2 Implement the record renderer per the design D3 table. Verify with unit tests: a full
  Traefik v3.7.13 JSON line maps to exactly the twelve fields with correct types; absent headers
  give `null`; `Duration` 32412345 gives `duration_ms` 32.412; an extra key such as `RouterName` or
  `ServiceURL` is not copied; a CLF line and malformed JSON render to `None`.

## 4. HTTP log endpoint

- [ ] 4.1 Add `GET /api/users/{user_id}/deployments/{deployment_id}/http-log` to
  `api/app/api/users.py` with `follow`, `tail`, `since` and `lookback`, authorized like the pod-log
  route, using the shared `stream_registry`. Verify with API tests: own deployment streams
  `event: request` records; another user's deployment gives 404; Loki unreachable before the first
  byte gives 503; a third open stream of either kind beyond the limit is refused; a
  selector-looking query parameter does not change the issued LogQL; an empty result is an empty
  stream ending with `end`.
- [ ] 4.2 Run the full `api/` suite (`-n 8`) and verify it is green.

## 5. Router-naming note

- [ ] 5.1 Add a comment beside the Traefik chart version variable in
  `tf/deps/system/helm/traefik/variables.tf` stating that the HTTP access log
  (`api/app/services/http_logs.py`) selects requests by Traefik's Ingress router-name format, and
  that `freepod log --http` should be checked after an upgrade. Verify with `terraform fmt -check`.

## 6. CLI

- [ ] 6.1 Add `--since DURATION` to `freepod log`, parsed as `^[1-9][0-9]*[smhd]$` and sent as
  `lookback` on the first connect only, never on a resume. Verify with CLI tests: valid forms send
  the right seconds; `1w`, `90` and `0m` are refused without a request; a platform 400 is reported
  with its reason; a reconnect sends `since` and no `lookback`.
- [ ] 6.2 Add `--json` for pod logs, printing each event's data as compact JSONL. Verify with a CLI
  test that every stdout line parses as an object with string `ts`, `line` and `release`, and that
  `-t` does not change it.
- [ ] 6.3 Add `--http`, which reads `…/http-log`, consumes `request` events through the existing
  follow and reconnect path, and formats Combined Log Format per design D5 (fixed English month
  names, Apache-style escaping, `-` for absent referer or user agent, `-t` prefix). `--http -r` is a
  usage error. Verify with CLI tests: the spec's typical-request line is reproduced exactly; a path
  containing `"` and a control character is escaped and stays one line; `--http --json` prints the
  record unchanged; `--http -r 3` exits non-zero before any request; "no requests" goes to stderr
  with exit 0.
- [ ] 6.4 Update the `log` command's help text for the three flags, and bump the client version
  per `cli-distribution`. Verify that `freepod log --help` lists them and the CLI suite passes.

## 7. Documentation

- [ ] 7.1 Document `--http`, `--json` and `--since` in `ui/docs/developers/logs-and-debugging.md`
  and `ui/docs/developers/cli-reference.md`, including that HTTP logs cannot be pinned to a release
  and that `-n` bounds a `--since` window. Verify that the docs site builds.
- [ ] 7.2 Update the `freepod log` row in `cli/README.md`, and mention `freepod log --http` in
  `cli/src/freepod/assets/SKILL.md`'s debugging guidance as the way to see whether requests reach
  the app. Verify that `cli/tests/test_skill.py` passes.

## 8. End-to-end on dev

- [ ] 8.1 With `traefik-json-access-logs` live and the API deployed to dev, run the new client
  against a dev deployment that serves two hostnames (an App Studio deployment). Verify that
  `freepod log --http -n 20` prints CLF lines for both hosts, `--json` shows both `host` values,
  `--since 5m -f` follows new requests, and `freepod log --since 1h --json` works for pod output.

## Workflow follow-up

- Deploy the API to prod before publishing the client (design: Migration Plan).
- Archive the change and sync its spec deltas.
