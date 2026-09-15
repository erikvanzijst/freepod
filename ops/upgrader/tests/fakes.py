"""In-memory stand-ins for the bucket and for GitHub."""

import json
from datetime import UTC, datetime, timedelta

import httpx


class MemoryStore:
    def __init__(self):
        self.objects: dict[str, tuple[bytes, str]] = {}

    def put(self, key, data, content_type):
        self.objects[key] = (data, content_type)

    def url(self, key):
        return f"https://blob.test/bucket/{key}?X-Amz-Expires=3600&X-Amz-Signature=sig"


class FakeGitHub:
    """Answers the App endpoints the service calls, and records every request."""

    def __init__(self, token_lifetime=timedelta(hours=1)):
        self.requests: list[httpx.Request] = []
        self.minted = 0
        self.token_lifetime = token_lifetime
        self.pulls: dict[int, dict] = {}
        self.down = False

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.down:
            raise httpx.ConnectError("unreachable", request=request)
        path = request.url.path
        if path == "/repos/erikvanzijst/freepod/installation":
            return httpx.Response(200, json={"id": 77})
        if path == "/app/installations/77/access_tokens":
            self.minted += 1
            expires = datetime.now(UTC) + self.token_lifetime
            return httpx.Response(201, json={
                "token": f"ghs_minted{self.minted}",
                "expires_at": expires.strftime("%Y-%m-%dT%H:%M:%SZ"),
            })
        if path == "/app":
            return httpx.Response(200, json={"slug": "freepod-upgrader"})
        if path in ("/users/freepod-upgrader[bot]", "/users/freepod-upgrader%5Bbot%5D"):
            return httpx.Response(200, json={"id": 4242, "login": "freepod-upgrader[bot]"})
        if path.startswith("/repos/erikvanzijst/freepod/pulls/"):
            number = int(path.rsplit("/", 1)[1])
            if number in self.pulls:
                return httpx.Response(200, json=self.pulls[number])
        return httpx.Response(404, json={"message": "Not Found"})

    def client(self) -> httpx.Client:
        return httpx.Client(base_url="https://api.github.com", transport=httpx.MockTransport(self.handler))

    def mint_bodies(self) -> list[dict]:
        return [json.loads(r.content) for r in self.requests if r.url.path.endswith("/access_tokens")]
