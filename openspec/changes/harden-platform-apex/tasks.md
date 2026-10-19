## 1. API

- [x] 1.1 Raise FastAPI to 0.141.1 (`strict_content_type` on by default) and lock it
- [x] 1.2 Read the subdomain write routes from the OpenAPI schema in `test_account_subdomain.py`, since FastAPI no longer flattens included routers into `app.routes`
- [x] 1.3 Full `api/` suite green

## 2. Edge

- [x] 2.1 oauth2-proxy: `cookie_name = "__Host-freepod_platform"`, `cookie_secure = true`, `cookie_samesite = "lax"`
- [x] 2.2 `apex-headers` Middleware in the login namespace, exported to the caelus module and attached to every apex route and the `/oauth2` route
- [x] 2.3 `strip-cookie` Middleware on the UI route
- [x] 2.4 Apex, webhook, `/oauth2` and broker routes on `websecure` only
- [x] 2.5 `headers-hsts` removes `Clear-Site-Data`
- [x] 2.6 Prod reserves `dev.freepod.eu`
- [x] 2.7 Drop `ui/nginx.conf`'s server-level `add_header` lines, which no location inherited

## 3. Request origin and framing

- [x] 3.1 `OriginGuard` on the API, trusting the CORS origins
- [x] 3.2 Verifier drops the session on state-changing requests and WebSocket handshakes from other origins' pages; `daemons/VERSION` 0.3.1, `app_auth_image` pinned to it
- [x] 3.3 App Studio `frame-self` Middleware on the studio Ingress; chart 0.2.13, catalog `chart_version` 0.2.13

## 4. Rollout and verification

- [x] 4.1 Apply `tf/deps` (cluster-wide `headers-hsts`)
- [x] 4.2 Publish `daemons:0.3.1` and the `appstudio` 0.2.13 chart; apply `tf/app` on dev, then rebuild and roll out the API image
- [x] 4.3 On dev: `http://` redirects to `https://`; apex responses carry the framing headers; login issues `__Host-freepod_platform*` cookies; sign-out clears them; a JSON body without `Content-Type` gets `422`; a `POST` with `Sec-Fetch-Site: same-site` gets `403`
- [ ] 4.4 Repeat 4.2–4.3 on prod; confirm a `dev` subdomain claim is refused there
- [x] 4.5 Move the dev studio to chart 0.2.13 and confirm it still loads opencode in its frame
- [ ] 4.6 Submit `freepod.eu` to the HSTS preload list
