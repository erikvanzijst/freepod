"""The HTTP client for the Freepod API, and the status-code contract it obeys.

The platform's authentication statuses invert the conventional reading, for
reasons recorded in design Appendix A. The short version:

| Status                                 | Answered by | Client action                      |
|----------------------------------------|-------------|------------------------------------|
| 401                                    | edge        | stop and explain; do not re-auth   |
| 403, non-JSON body                     | edge        | refresh once and retry             |
| 403, JSON `detail`                     | API         | stop — a permission error          |
| 404, `{"detail": "Not authenticated"}` | API         | report a platform condition        |

The two 403 rows are why the rule cannot simply be "403 means refresh": the API
issues its own 403s from `require_self` / `require_admin`, and an unbounded
refresh rule would refresh, fail, re-login, and loop on a request that no
credential can satisfy. Hence: **refresh at most once per request**.

One asymmetry worth knowing while reading this module: most of the reads the
client performs later — products, plans, hostnames, domains — are on the edge's
`skip_auth_routes` list and are answered anonymously whatever credential the
request carried. They cannot return 401 or 403, so none of the machinery below
ever fires on them. That is exactly why `GET /api/me` must come first.
"""

from __future__ import annotations

import time
from contextlib import contextmanager
from typing import Any, Iterator, Optional
from urllib.parse import quote

import httpx

from . import AuthenticationError, FreepodError, PermissionError_
from .auth import Session
from .config import DEFAULT_HTTP_TIMEOUT, USER_AGENT, Environment

#: Methods whose repetition cannot create or duplicate state.
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})

#: Total attempts for a safe request, including the first.
MAX_ATTEMPTS = 3

#: First backoff interval; doubles per attempt.
BACKOFF_BASE_SECONDS = 0.5


def _json_code(response: httpx.Response) -> Optional[str]:
    """The `code` of a JSON error body, or None.

    Several refusals share a status; the platform gives the ones worth telling
    apart a stable identifier, and matching that is what keeps a client from
    depending on prose it does not own.
    """
    try:
        payload = response.json()
    except ValueError:
        return None
    if isinstance(payload, dict) and isinstance(payload.get("code"), str):
        return payload["code"]
    return None


def _json_detail(response: httpx.Response) -> Optional[str]:
    """The `detail` of a JSON error body, or None if the body is not one.

    Identification is by *body shape*, not by `Content-Type`: the edge's
    refusals are a bare `http.Error` with a plain-text body and no reliable
    content type, while every refusal the API itself issues is a FastAPI JSON
    document carrying `detail`.
    """
    try:
        payload = response.json()
    except ValueError:
        return None
    if isinstance(payload, dict) and isinstance(payload.get("detail"), str):
        return payload["detail"]
    return None


class ApiClient:
    """Authenticated access to one environment's REST API."""

    def __init__(
        self,
        env: Environment,
        session: Session,
        *,
        timeout: int = DEFAULT_HTTP_TIMEOUT,
        verbose: bool = False,
        client: Optional[httpx.Client] = None,
        backoff_base: float = BACKOFF_BASE_SECONDS,
    ):
        self.env = env
        self.session = session
        self.timeout = timeout
        self.verbose = verbose
        self.backoff_base = backoff_base
        self._client = client if client is not None else httpx.Client()
        self._owns_client = client is None

    # -- lifecycle --------------------------------------------------------

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def __enter__(self) -> "ApiClient":
        return self

    def __exit__(self, *exc_info) -> None:
        self.close()

    # -- requests ---------------------------------------------------------

    def request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        """Perform a request, applying the status-code contract.

        Returns the response for any status the contract does not claim, so a
        caller that needs to distinguish, say, the two causes of a 409 still
        can. Raises for every credential-related status.
        """
        url = self.env.url(path)
        refreshed = False

        while True:
            response = self._send(method, url, **kwargs)
            status = response.status_code

            if status == 401:
                # Either no credential reached the edge, or — on dev only — a
                # perfectly valid one belongs to a non-member of the gating
                # group. Re-authenticating succeeds and changes nothing, so
                # this never triggers a login.
                raise AuthenticationError(self._unauthenticated_message(url))

            if status == 403:
                detail = _json_detail(response)
                if detail is not None:
                    # The API answered: authenticated, but not permitted here.
                    raise PermissionError_(f"403 from {url} — {detail}")
                if refreshed:
                    # Bounded refresh: a second 403 is reported, never retried.
                    raise PermissionError_(
                        f"403 from {url} even after refreshing — the token is still not "
                        f"verifiable. Run `freepod login --env {self.env.name}` to "
                        f"re-authenticate from scratch."
                    )
                refreshed = True
                self._renew()
                continue

            if status == 404 and _json_detail(response) == "Not authenticated":
                # Only reachable on a route the edge skips. A bug report, not a
                # login prompt.
                raise FreepodError(
                    f"404 'Not authenticated' from {url} — no identity reached the API. "
                    "This is an unexpected platform condition, not a credential problem; "
                    "please report it."
                )

            return response

    @contextmanager
    def stream(
        self,
        method: str,
        path: str,
        *,
        timeout: Any = None,
        **kwargs: Any,
    ) -> Iterator[httpx.Response]:
        """Open a streaming response, under the same contract as `request`.

        A separate method rather than a flag on `request` because the two
        cannot share a return type: `request` hands back a response whose body
        is already in memory, while this yields one whose body is still
        arriving and must be consumed inside the `with`.

        The contract itself is *not* reimplemented -- 401, the two flavours of
        403, and the platform's odd 404 are decided by the same rules, and a
        refresh still happens at most once. What differs is the mechanics: the
        stream has to be opened to see the status at all, so a refusal means
        closing it, refreshing, and opening a second one.

        Retries are deliberately absent. `_send`'s three attempts exist for
        idempotent *short* requests; replaying a long-lived stream would
        re-deliver everything the caller had already consumed, and the caller
        knows how to resume from where it stopped, which this does not.
        """
        url = self.env.url(path)
        caller_headers = dict(kwargs.pop("headers", None) or {})
        refreshed = False

        while True:
            headers = dict(self._headers())
            headers.update(caller_headers)
            try:
                opened = self._client.stream(
                    method, url, headers=headers, timeout=timeout, **kwargs
                )
            except httpx.HTTPError as exc:
                raise FreepodError(f"cannot reach {url}: {exc}") from None

            with opened as response:
                status = response.status_code
                if status >= 400:
                    # The body decides between the two 403s and identifies the
                    # platform's 404, and on a streaming response it has to be
                    # pulled in explicitly before it can be read.
                    response.read()

                if status == 401:
                    raise AuthenticationError(self._unauthenticated_message(url))

                if status == 403:
                    detail = _json_detail(response)
                    if detail is not None:
                        raise PermissionError_(f"403 from {url} — {detail}")
                    if refreshed:
                        raise PermissionError_(
                            f"403 from {url} even after refreshing — the token is still "
                            f"not verifiable. Run `freepod login --env {self.env.name}` "
                            f"to re-authenticate from scratch."
                        )
                    refreshed = True
                    self._renew()
                    # Leaves the `with`, closing this stream before the retry
                    # opens another.
                    continue

                if status == 404 and _json_detail(response) == "Not authenticated":
                    raise FreepodError(
                        f"404 'Not authenticated' from {url} — no identity reached the "
                        f"API. This is an unexpected platform condition, not a "
                        f"credential problem; please report it."
                    )

                yield response
                return

    def get(self, path: str, **kwargs: Any) -> httpx.Response:
        return self.request("GET", path, **kwargs)

    def post(self, path: str, **kwargs: Any) -> httpx.Response:
        return self.request("POST", path, **kwargs)

    def put(self, path: str, **kwargs: Any) -> httpx.Response:
        return self.request("PUT", path, **kwargs)

    def delete(self, path: str, **kwargs: Any) -> httpx.Response:
        return self.request("DELETE", path, **kwargs)

    def get_json(self, path: str, **kwargs: Any) -> Any:
        """GET and decode, raising on any non-successful status."""
        return self._decode(self.get(path, **kwargs))

    def me(self) -> dict:
        """`GET /api/me` — the first request that actually exercises the token.

        Every command that requires authentication calls this before its public
        reads, so a bad credential is reported here rather than surfacing later
        as an unrelated-looking failure. See design D15.
        """
        body = self.get_json("/api/me")
        if not isinstance(body, dict) or "id" not in body:
            raise FreepodError(f"unexpected /api/me response: {body!r}")
        return body

    def subdomain(self) -> dict:
        """`GET /api/me/subdomain` — always 200, even before one is claimed.

        `subdomain` and `fqdn` are null until the account holds one; `domain` is
        the platform's own and is reported either way.
        """
        body = self.get_json("/api/me/subdomain")
        if not isinstance(body, dict):
            raise FreepodError(f"unexpected /api/me/subdomain response: {body!r}")
        return body

    def check_hostname(self, fqdn: str) -> dict:
        """`GET /api/hostnames/{fqdn}` — always 200 with `{fqdn, usable, reason}`.

        Authenticated: the answer depends on who is asking, since an application
        name is only usable beneath the caller's own domain name.

        Advisory only: the name is claimed when the deployment is created, so a
        usable answer here is not a reservation. Note the check runs without
        `exclude_deployment_id`, so re-checking a name we already hold reports
        `in_use` against ourselves — see design D14.
        """
        body = self.get_json(f"/api/hostnames/{quote(fqdn, safe='')}")
        if not isinstance(body, dict):
            raise FreepodError(f"unexpected hostname check response: {body!r}")
        return body

    # -- public reads -----------------------------------------------------
    #
    # Everything below is on the edge's `skip_auth_routes` list and is answered
    # anonymously. Call `me()` before any of them, or a credential problem
    # surfaces later as an unrelated-looking failure.

    def products(self) -> list:
        body = self.get_json("/api/products")
        if not isinstance(body, list):
            raise FreepodError(f"unexpected /api/products response: {body!r}")
        return body

    def find_product(self, slug: str) -> Optional[dict]:
        """The first product carrying `slug`, or None.

        By slug, never by display name: `slug` is written only by the catalog
        reconciler and is the product's stable identity, while the name is
        presentation and can be retitled at any time.
        """
        for product in self.products():
            if isinstance(product, dict) and product.get("slug") == slug:
                return product
        return None

    def ssh_edge(self) -> dict:
        """`GET /api/ssh` — this environment's edge address and host key."""
        body = self.get_json("/api/ssh")
        if not isinstance(body, dict):
            raise FreepodError(f"unexpected /api/ssh response: {body!r}")
        return body

    # -- internals --------------------------------------------------------

    def _headers(self) -> dict:
        headers = {"Accept": "application/json", "User-Agent": USER_AGENT}
        if self.session.access_token:
            headers["Authorization"] = f"Bearer {self.session.access_token}"
        return headers

    def _send(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        """Send one request, retrying only what is safe to repeat.

        A request that could create or mutate state gets exactly one attempt:
        a duplicate build or deployment is worse than a reported failure.
        """
        attempts = MAX_ATTEMPTS if method.upper() in SAFE_METHODS else 1
        # Load-bearing, not incidental: caller-supplied headers are *read*,
        # never written. The copy is what lets `request()` replay this call
        # after a refresh with the caller's headers intact and a fresh
        # Authorization. Merging the other way — injecting auth into the
        # caller's dict, or dropping this `dict()` so `update` writes into a
        # hoisted base — reintroduces two bugs at once: a stale token that the
        # bounded-refresh rule then misreports as a permission error, and a
        # `Range` from one request leaking into the next.
        headers = dict(self._headers())
        headers.update(kwargs.pop("headers", None) or {})
        timeout = kwargs.pop("timeout", self.timeout)

        last_error: Optional[Exception] = None
        for attempt in range(1, attempts + 1):
            try:
                response = self._client.request(
                    method, url, headers=headers, timeout=timeout, **kwargs
                )
            except httpx.HTTPError as exc:
                last_error = exc
                if attempt >= attempts:
                    raise FreepodError(f"cannot reach {url}: {exc}") from None
                self._backoff(attempt)
                continue

            if response.status_code >= 500 and attempt < attempts:
                self._backoff(attempt)
                continue
            return response

        # Unreachable: the loop either returns or raises.
        raise FreepodError(f"cannot reach {url}: {last_error}")

    def _backoff(self, attempt: int) -> None:
        delay = self.backoff_base * (2 ** (attempt - 1))
        if delay > 0:
            time.sleep(delay)

    def _renew(self) -> None:
        """Recover from an edge 403 — the token is expired or unverifiable.

        A refused refresh falls back to a full login rather than failing
        outright, which is what makes an idle-expired offline session recover
        without the user being told to do anything.
        """
        if self.session.refresh():
            self.session.credential_source = "refreshed token"
            return
        self.session.login()
        self.session.credential_source = "fresh login (after failed refresh)"

    def _unauthenticated_message(self, url: str) -> str:
        if self.env.requires_group:
            return (
                f"401 from {url} — no credential, or your account lacks access to "
                f"'{self.env.name}'.\n"
                f"  {self.env.api_base} requires membership of the "
                f"'{self.env.requires_group}' Keycloak group.\n"
                f"  Re-authenticating will succeed and change nothing — check the "
                f"group membership first."
            )
        return (
            f"401 from {url} — no credential reached the API.\n"
            f"  Run `freepod login --env {self.env.name}` to authenticate."
        )

    @staticmethod
    def _decode(response: httpx.Response) -> Any:
        if not response.is_success:
            detail = _json_detail(response)
            body = detail if detail is not None else response.text.strip()[:300]
            raise FreepodError(f"HTTP {response.status_code} from {response.url}: {body}")
        try:
            return response.json()
        except ValueError:
            raise FreepodError(f"unparseable response from {response.url}") from None
