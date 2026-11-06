"""The parking page, and the host guard that lets the API serve it (parking-page).

A stopped deployment's Ingress routes its hostname to this API through an
ExternalName Service, bypassing the forward-auth on the API's own Ingresses. So
any request whose ``Host`` is not the platform's own domain is answered here,
before any middleware or route runs, whatever identity headers it carries.
"""

from __future__ import annotations

import html
from string import Template

from starlette.types import ASGIApp, Receive, Scope, Send

from app.config import get_settings

# The connection's own peer. uvicorn rewrites it from X-Forwarded-For only for
# `--forwarded-allow-ips` (default 127.0.0.1), which must never be widened.
LOOPBACK = {"127.0.0.1", "::1"}

_PAGE = Template("""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>$host is stopped</title>
<style>
  :root {
    color-scheme: light dark;
    --bg: #fcfcfb;
    --fg: #1a1a18;
    --muted: #71716a;
    --rule: #e4e4de;
    --dot: #b8b8ae;
  }
  @media (prefers-color-scheme: dark) {
    :root {
      --bg: #161614;
      --fg: #edece7;
      --muted: #99988e;
      --rule: #2e2e2a;
      --dot: #5d5d55;
    }
  }
  * { box-sizing: border-box; }
  html, body { height: 100%; }
  body {
    margin: 0;
    display: flex;
    align-items: center;
    justify-content: center;
    padding: 2rem 1.5rem;
    background: var(--bg);
    color: var(--fg);
    font-family: ui-sans-serif, system-ui, -apple-system, "Segoe UI", Roboto,
      "Helvetica Neue", Arial, sans-serif;
    line-height: 1.6;
    -webkit-font-smoothing: antialiased;
    -moz-osx-font-smoothing: grayscale;
  }
  main { max-width: 30rem; text-align: center; }
  .dot {
    width: 0.5rem;
    height: 0.5rem;
    margin: 0 auto 2rem;
    border-radius: 50%;
    background: var(--dot);
    opacity: 0.7;
  }
  h1 {
    margin: 0 0 0.75rem;
    font-size: 1.375rem;
    font-weight: 600;
    letter-spacing: -0.012em;
    overflow-wrap: anywhere;
  }
  p { margin: 0; color: var(--muted); font-size: 0.9375rem; text-wrap: pretty; }
  footer {
    margin-top: 2.5rem;
    padding-top: 1.5rem;
    border-top: 1px solid var(--rule);
    color: var(--muted);
    font-size: 0.8125rem;
    letter-spacing: 0.02em;
  }
</style>
</head>
<body>
  <main>
    <div class="dot" aria-hidden="true"></div>
    <h1>$host is stopped.</h1>
    <p>Its owner has stopped this app. Its data is kept, and it will be served here again once it is started.</p>
    <footer>Freepod</footer>
  </main>
</body>
</html>
""")


def _header(scope: Scope, name: bytes) -> str:
    for key, value in scope.get("headers") or []:
        if key == name:
            return value.decode("latin-1")
    return ""


def request_host(scope: Scope) -> str:
    """The ``Host`` header, lowercased and without its port."""
    host = _header(scope, b"host").strip().lower()
    if host.startswith("["):  # [::1]:8000
        return host[: host.find("]") + 1] if "]" in host else host
    return host.rsplit(":", 1)[0] if host.count(":") == 1 else host


def _is_browser_navigation(scope: Scope) -> bool:
    return (
        scope.get("method") == "GET"
        and "text/html" in _header(scope, b"accept").lower()
        and not _header(scope, b"upgrade")
    )


class ParkingGuard:
    """Answer every request for a host other than the platform's own domain
    with the parking response. Installed outermost."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] not in ("http", "websocket") or self._passes(scope):
            await self.app(scope, receive, send)
            return
        if scope["type"] == "websocket":
            # Closing before accept is answered with 403; nothing is upgraded.
            await send({"type": "websocket.close", "code": 1008})
            return
        await self._park(scope, send)

    @staticmethod
    def _passes(scope: Scope) -> bool:
        domain = get_settings().domain.strip().lower()
        if not domain:
            return True
        client = scope.get("client")
        if client and client[0] in LOOPBACK:
            return True
        return request_host(scope) == domain

    @staticmethod
    async def _park(scope: Scope, send: Send) -> None:
        host = request_host(scope)
        if _is_browser_navigation(scope):
            body = _PAGE.substitute(host=html.escape(host, quote=True)).encode()
            content_type = b"text/html; charset=utf-8"
        else:
            body = f"{host} is stopped.\n".encode()
            content_type = b"text/plain; charset=utf-8"
        await send(
            {
                "type": "http.response.start",
                "status": 503,
                "headers": [
                    (b"content-type", content_type),
                    (b"content-length", str(len(body)).encode()),
                    (b"cache-control", b"no-store"),
                ],
            }
        )
        await send({"type": "http.response.body", "body": body})
