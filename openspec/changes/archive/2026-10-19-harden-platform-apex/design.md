## Context

See proposal.md. Behavior verified before writing this change:

- Traefik 3.7 `headers` middleware: an empty `customRequestHeaders` value
  removes the request header and an empty `customResponseHeaders` value removes
  the response header. A `forwardAuth` earlier in the chain still receives the
  `Cookie` a later middleware strips.
- oauth2-proxy 7.14 accepts a `__Host-` cookie name and emits its chunk and
  `_csrf` cookies under the same prefix, with `Path=/` and no `Domain`.
- nginx drops server-level `add_header` directives from any location that sets
  its own, and every UI location does, so the UI's `X-Frame-Options` was never
  sent.

## Decisions

### D1: Strip `Cookie` on the UI route only

The SPA reads no cookie, so nginx is given none. The API routes need the
header for `forward-auth`, which reads it before the request reaches the API. The `/oauth2` endpoints need it
for the CSRF and session cookies.

### D2: Apex headers live beside `forward-auth`, in the login namespace

The platform Traefik does not enable `allowCrossNamespace`, so the `/oauth2`
IngressRoute (login namespace) can only reference a Middleware in its own
namespace. The caelus Ingresses reference it by provider name, the same way
they already reference `forward-auth`. The name reaches the caelus module as a
module output, so Terraform creates the Middleware before any Ingress points at
it.

### D3: `Clear-Site-Data` is removed in the shared `websecure` middleware

`Clear-Site-Data: "cookies"` applies beyond the host that sends it, and no
platform route sends it. The entrypoint's existing default middleware already
covers every route. Adding a second default middleware would reopen the window
in which Traefik serves 500s until a newly referenced middleware exists.
Custom-domain apps lose the header as well; the edge cannot tell an app's
hostname kind apart, and no catalog product sends it.

### D4: FastAPI 0.141.1

`strict_content_type` defaults on since 0.132.0. 0.141.1 is the newest release
older than two months. Later releases were arriving several a day and the
newest added a dependency.

### D5: The verifier drops the session rather than refusing

A state-changing request from another origin's page is judged as if it carried
no session, so the existing rules decide the rest: a public path still serves
it anonymously, and anything else gets the `401` an unauthenticated request
gets. A public endpoint that legitimately receives cross-site posts keeps
working, without an identity attached.

### D6: The studio sets `X-Frame-Options`, not a CSP

A Traefik `contentSecurityPolicy` replaces whatever policy the upstream sends,
and opencode may send its own. `X-Frame-Options: SAMEORIGIN` restricts framing
without touching it, and the chrome frames opencode from the same origin.

## Risks / Trade-offs

- **[Forced re-login]** Renaming the cookie invalidates every session once. The
  old `_oauth2_proxy*` cookies are ignored and expire on their own.
- **[An apex client that sends a JSON body with no `Content-Type`]** It now gets
  `422`. The UI and the `freepod` CLI both declare `application/json`.
