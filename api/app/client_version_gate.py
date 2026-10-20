from __future__ import annotations

import json
import re

from packaging.version import InvalidVersion, Version
from starlette.types import ASGIApp, Receive, Scope, Send

# The oldest `freepod` CLI release the API supports. Raised in the same change
# as any backend change a released client cannot survive.
MIN_CLIENT_VERSION = Version("0.22.0")

_CLIENT_AGENT = re.compile(r"^freepod/(\S+)")


class ClientVersionGate:
    """Refuse every request from a `freepod` CLI older than `MIN_CLIENT_VERSION`
    with 426, before routing, so the user is told to upgrade instead of meeting
    whatever the old client makes of a changed API.

    Only the platform's own client is gated: any other `User-Agent`, or one
    whose version cannot be parsed, passes.
    """

    def __init__(self, app: ASGIApp, minimum: Version = MIN_CLIENT_VERSION) -> None:
        self.app = app
        self.minimum = minimum

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http" and self._outdated(scope):
            body = json.dumps(
                {
                    "detail": (
                        f"This version of freepod is no longer supported; version "
                        f"{self.minimum} or later is required. Upgrade `freepod` to continue "
                        f"(uv tool update freepod || brew upgrade freepod || pip install --upgrade freepod)."
                    ),
                    "code": "client_upgrade_required",
                }
            ).encode()
            await send(
                {
                    "type": "http.response.start",
                    "status": 426,
                    "headers": [
                        (b"content-type", b"application/json"),
                        (b"content-length", str(len(body)).encode()),
                    ],
                }
            )
            await send({"type": "http.response.body", "body": body})
            return
        await self.app(scope, receive, send)

    def _outdated(self, scope: Scope) -> bool:
        agent = next(
            (v.decode("latin-1") for k, v in scope["headers"] if k.lower() == b"user-agent"), ""
        )
        match = _CLIENT_AGENT.match(agent)
        if match is None:
            return False
        try:
            return Version(match.group(1)) < self.minimum
        except InvalidVersion:
            return False
