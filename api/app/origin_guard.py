from __future__ import annotations

import json
from collections.abc import Iterable
from urllib.parse import urlsplit

from starlette.types import ASGIApp, Receive, Scope, Send

SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


class OriginGuard:
    """Refuse state-changing requests a browser started from a page on another
    origin, unless that origin is trusted.

    `Sec-Fetch-Site` decides when the browser sends it; `Origin` is the
    fallback. A request with neither (the CLI, webhooks, the registry's token
    exchange) is not from a browser page and passes.
    """

    def __init__(self, app: ASGIApp, trusted_origins: Iterable[str] = ()) -> None:
        self.app = app
        self.trusted = frozenset(o.lower() for o in trusted_origins)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http" and scope["method"] not in SAFE_METHODS and self._foreign(scope):
            body = json.dumps({"detail": "Cross-origin request refused"}).encode()
            await send(
                {
                    "type": "http.response.start",
                    "status": 403,
                    "headers": [
                        (b"content-type", b"application/json"),
                        (b"content-length", str(len(body)).encode()),
                    ],
                }
            )
            await send({"type": "http.response.body", "body": body})
            return
        await self.app(scope, receive, send)

    def _foreign(self, scope: Scope) -> bool:
        headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope["headers"]}
        origin = headers.get("origin", "").lower()
        if origin in self.trusted:
            return False
        site = headers.get("sec-fetch-site", "").lower()
        if site:
            return site not in ("same-origin", "none")
        if origin:
            return urlsplit(origin).netloc != headers.get("host", "").lower()
        return False
