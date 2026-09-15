"""Redaction by value (D10, product-upgrade-history)."""

from __future__ import annotations

import base64
import binascii

TOKEN_MARKER = "[redacted:github-token]"
KEY_MARKER = "[redacted:GITHUB_APP_PRIVATE_KEY]"


def key_values(private_key_b64: str | None) -> list[str]:
    """The var's value, the PEM it decodes to, and each line of the PEM's body."""
    if not private_key_b64:
        return []
    values = [private_key_b64]
    try:
        pem = base64.b64decode(private_key_b64, validate=True).decode()
    except (binascii.Error, UnicodeDecodeError):
        return values
    values.append(pem.strip())
    values += [line.strip() for line in pem.splitlines() if line.strip() and not line.startswith("-----")]
    return values


class Redactor:
    def __init__(self, secrets: dict[str, str] | None = None, private_key_b64: str | None = None):
        self._pairs: dict[bytes, bytes] = {}
        for name, value in (secrets or {}).items():
            self._add(value, f"[redacted:{name}]")
        for value in key_values(private_key_b64):
            self._add(value, KEY_MARKER)

    def _add(self, value: str | None, marker: str) -> None:
        if value:
            self._pairs[value.encode()] = marker.encode()

    def add_token(self, token: str) -> None:
        self._add(token, TOKEN_MARKER)

    def bytes(self, data: bytes) -> bytes:
        for value in sorted(self._pairs, key=len, reverse=True):
            data = data.replace(value, self._pairs[value])
        return data

    def __call__(self, text: str | None) -> str | None:
        return None if text is None else self.bytes(text.encode()).decode()
