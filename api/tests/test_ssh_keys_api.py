"""The `/api/users/{user_id}/ssh-keys` collection."""

from __future__ import annotations

import base64
import hashlib
import itertools
import subprocess
from pathlib import Path
from urllib.parse import quote

import pytest

from tests.conftest import (
    ADMIN_EMAIL,
    OTHER_AUTH_HEADER,
    OTHER_EMAIL,
    USER_AUTH_HEADER,
    USER_EMAIL,
    create_user,
    subject_for,
)

AUTH_ADMIN = {
    "X-Auth-Request-Email": ADMIN_EMAIL,
    "X-Auth-Request-User": subject_for(ADMIN_EMAIL),
}
_counter = itertools.count()


def pub(tmp_path: Path, key_type="ed25519", extra=(), comment="alice@laptop") -> str:
    path = tmp_path / f"{key_type}-{next(_counter)}"
    subprocess.run(
        ["ssh-keygen", "-t", key_type, "-N", "", "-C", comment, "-f", str(path), *extra],
        check=True,
        capture_output=True,
    )
    return Path(str(path) + ".pub").read_text().strip()


def key_with_fingerprint_containing(tmp_path: Path, needle: str) -> str:
    """Generate keys until one's fingerprint contains `needle`.

    Roughly half of all fingerprints contain `/` and half contain `+`, so this
    terminates almost immediately.
    """
    for _ in range(200):
        line = pub(tmp_path)
        blob = base64.b64decode(line.split()[1])
        digest = base64.b64encode(hashlib.sha256(blob).digest()).decode().rstrip("=")
        if needle in digest:
            return line
    raise AssertionError(f"no fingerprint containing {needle!r} in 200 keys")


@pytest.fixture
def user(client):
    return create_user(client, USER_EMAIL)


def url(user_id, fingerprint=None):
    base = f"/api/users/{user_id}/ssh-keys"
    return base if fingerprint is None else f"{base}/{quote(fingerprint, safe='')}"


# --- Shape -----------------------------------------------------------------


def test_empty_collection_is_an_empty_array(client, user):
    resp = client.get(url(user["id"]), headers=USER_AUTH_HEADER)
    assert resp.status_code == 200
    assert resp.json() == []


def test_add_returns_201_with_location(client, user, tmp_path):
    resp = client.post(
        url(user["id"]), json={"public_key": pub(tmp_path)}, headers=USER_AUTH_HEADER
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["fingerprint"].startswith("SHA256:")
    assert body["key_type"] == "ssh-ed25519"
    assert body["bits"] == 256
    assert body["label"] == "alice@laptop"
    assert resp.headers["Location"] == url(user["id"], body["fingerprint"])


def test_list_add_and_single_read_agree_on_shape(client, user, tmp_path):
    added = client.post(
        url(user["id"]), json={"public_key": pub(tmp_path)}, headers=USER_AUTH_HEADER
    ).json()
    listed = client.get(url(user["id"]), headers=USER_AUTH_HEADER).json()
    single = client.get(
        url(user["id"], added["fingerprint"]), headers=USER_AUTH_HEADER
    ).json()

    assert len(listed) == 1
    assert added == listed[0] == single


def test_location_header_resolves(client, user, tmp_path):
    resp = client.post(
        url(user["id"]), json={"public_key": pub(tmp_path)}, headers=USER_AUTH_HEADER
    )
    follow = client.get(resp.headers["Location"], headers=USER_AUTH_HEADER)
    assert follow.status_code == 200
    assert follow.json() == resp.json()


def test_stored_body_drops_the_comment(client, user, tmp_path):
    line = pub(tmp_path, comment="alice@laptop")
    body = client.post(
        url(user["id"]), json={"public_key": line}, headers=USER_AUTH_HEADER
    ).json()
    assert body["public_key"] == " ".join(line.split()[:2])
    assert body["label"] == "alice@laptop"


def test_no_response_carries_private_material(client, user, tmp_path):
    client.post(url(user["id"]), json={"public_key": pub(tmp_path)}, headers=USER_AUTH_HEADER)
    text = client.get(url(user["id"]), headers=USER_AUTH_HEADER).text
    assert "PRIVATE KEY" not in text


# --- Fingerprints in URLs --------------------------------------------------


@pytest.mark.parametrize("needle", ["/", "+"])
def test_fingerprint_with_url_hostile_character_addresses_its_key(
    client, user, tmp_path, needle
):
    """About half of all fingerprints contain each of these.

    An ordinary path segment 404s on `/`, and a query parameter decodes `+`
    to a space — either would report "no such key" for a key that exists,
    on the one operation that revokes a lost machine's access.
    """
    line = key_with_fingerprint_containing(tmp_path, needle)
    added = client.post(
        url(user["id"]), json={"public_key": line}, headers=USER_AUTH_HEADER
    ).json()
    assert needle in added["fingerprint"]

    read = client.get(url(user["id"], added["fingerprint"]), headers=USER_AUTH_HEADER)
    assert read.status_code == 200
    assert read.json()["fingerprint"] == added["fingerprint"]

    deleted = client.delete(
        url(user["id"], added["fingerprint"]), headers=USER_AUTH_HEADER
    )
    assert deleted.status_code == 204
    assert client.get(url(user["id"]), headers=USER_AUTH_HEADER).json() == []


# --- Validation ------------------------------------------------------------


@pytest.mark.parametrize(
    "submission,expected_code",
    [
        ("gibberish", "malformed_key"),
        ("-----BEGIN OPENSSH PRIVATE KEY-----\nx\n-----END OPENSSH PRIVATE KEY-----",
         "private_key_material"),
    ],
)
def test_validation_failures_carry_a_code(client, user, submission, expected_code):
    resp = client.post(
        url(user["id"]), json={"public_key": submission}, headers=USER_AUTH_HEADER
    )
    assert resp.status_code == 400
    assert resp.json()["code"] == expected_code


def test_undersized_rsa_is_refused(client, user, tmp_path):
    resp = client.post(
        url(user["id"]),
        json={"public_key": pub(tmp_path, "rsa", ("-b", "1024"))},
        headers=USER_AUTH_HEADER,
    )
    assert resp.status_code == 400
    assert resp.json()["code"] == "key_too_short"


def test_multiple_keys_are_refused(client, user, tmp_path):
    resp = client.post(
        url(user["id"]),
        json={"public_key": pub(tmp_path) + "\n" + pub(tmp_path)},
        headers=USER_AUTH_HEADER,
    )
    assert resp.status_code == 400
    assert resp.json()["code"] == "multiple_keys"
    assert client.get(url(user["id"]), headers=USER_AUTH_HEADER).json() == []


def test_duplicate_is_409_and_distinguishable(client, user, tmp_path):
    line = pub(tmp_path)
    client.post(url(user["id"]), json={"public_key": line}, headers=USER_AUTH_HEADER)
    resp = client.post(url(user["id"]), json={"public_key": line}, headers=USER_AUTH_HEADER)
    assert resp.status_code == 409
    assert resp.json()["code"] == "duplicate_key"


def test_supplied_fingerprint_is_refused(client, user, tmp_path):
    resp = client.post(
        url(user["id"]),
        json={"public_key": pub(tmp_path), "fingerprint": "SHA256:whatever"},
        headers=USER_AUTH_HEADER,
    )
    assert resp.status_code == 422
    assert client.get(url(user["id"]), headers=USER_AUTH_HEADER).json() == []


def test_commentless_key_is_returned_with_a_null_label(client, user, tmp_path):
    line = " ".join(pub(tmp_path).split()[:2])
    body = client.post(
        url(user["id"]), json={"public_key": line}, headers=USER_AUTH_HEADER
    ).json()
    assert body["label"] is None
    assert client.get(url(user["id"]), headers=USER_AUTH_HEADER).json()[0]["label"] is None


def test_label_is_optional_and_defaults(client, user, tmp_path):
    body = client.post(
        url(user["id"]),
        json={"public_key": pub(tmp_path, comment="bob@desktop")},
        headers=USER_AUTH_HEADER,
    ).json()
    assert body["label"] == "bob@desktop"


# --- Authorization ---------------------------------------------------------


def test_non_owner_cannot_read(client, user, tmp_path):
    create_user(client, OTHER_EMAIL)
    resp = client.get(url(user["id"]), headers=OTHER_AUTH_HEADER)
    assert resp.status_code == 403


def test_admin_may_read_and_revoke(client, user, tmp_path):
    added = client.post(
        url(user["id"]), json={"public_key": pub(tmp_path)}, headers=USER_AUTH_HEADER
    ).json()

    assert client.get(url(user["id"]), headers=AUTH_ADMIN).status_code == 200
    assert (
        client.delete(url(user["id"], added["fingerprint"]), headers=AUTH_ADMIN).status_code
        == 204
    )
    assert client.get(url(user["id"]), headers=USER_AUTH_HEADER).json() == []


def test_admin_may_not_add(client, user, tmp_path):
    """Installing a key on another account is impersonation, not administration."""
    resp = client.post(
        url(user["id"]), json={"public_key": pub(tmp_path)}, headers=AUTH_ADMIN
    )
    assert resp.status_code == 403
    assert client.get(url(user["id"]), headers=USER_AUTH_HEADER).json() == []


def test_admin_refusal_is_distinguishable_from_validation(client, user, tmp_path):
    forbidden = client.post(
        url(user["id"]), json={"public_key": pub(tmp_path)}, headers=AUTH_ADMIN
    )
    invalid = client.post(
        url(user["id"]), json={"public_key": "gibberish"}, headers=USER_AUTH_HEADER
    )
    assert forbidden.status_code == 403
    assert invalid.status_code == 400
    assert "code" not in forbidden.json()


def test_non_owner_cannot_add(client, user, tmp_path):
    create_user(client, OTHER_EMAIL)
    resp = client.post(
        url(user["id"]), json={"public_key": pub(tmp_path)}, headers=OTHER_AUTH_HEADER
    )
    assert resp.status_code == 403


# --- Deletion --------------------------------------------------------------


def test_delete_removes_the_key(client, user, tmp_path):
    added = client.post(
        url(user["id"]), json={"public_key": pub(tmp_path)}, headers=USER_AUTH_HEADER
    ).json()
    assert client.delete(
        url(user["id"], added["fingerprint"]), headers=USER_AUTH_HEADER
    ).status_code == 204
    assert client.get(url(user["id"]), headers=USER_AUTH_HEADER).json() == []


def test_delete_of_unknown_fingerprint_is_404_not_403(client, user):
    resp = client.delete(url(user["id"], "SHA256:notarealfingerprint"), headers=USER_AUTH_HEADER)
    assert resp.status_code == 404


def test_delete_does_not_reach_another_account(client, user, tmp_path):
    other = create_user(client, OTHER_EMAIL)
    added = client.post(
        url(user["id"]), json={"public_key": pub(tmp_path)}, headers=USER_AUTH_HEADER
    ).json()
    resp = client.delete(url(other["id"], added["fingerprint"]), headers=OTHER_AUTH_HEADER)
    assert resp.status_code == 404
    assert len(client.get(url(user["id"]), headers=USER_AUTH_HEADER).json()) == 1


def test_no_root_level_collection(client):
    assert client.get("/api/ssh-keys", headers=USER_AUTH_HEADER).status_code == 404
