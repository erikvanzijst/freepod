"""Validation, fingerprinting and storage for account SSH keys."""

from __future__ import annotations

import base64
import itertools
import struct
import subprocess
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlmodel import Session

from app.models import SshKeyORM, UserORM
from app.services import ssh_keys as service
from app.services import users as user_service
from app.services.errors import NotFoundException

KEY_TYPES = [
    ("ed25519", [], "ssh-ed25519", 256),
    ("rsa", ["-b", "2048"], "ssh-rsa", 2048),
    ("rsa", ["-b", "4096"], "ssh-rsa", 4096),
    ("ecdsa", ["-b", "256"], "ecdsa-sha2-nistp256", 256),
    ("ecdsa", ["-b", "384"], "ecdsa-sha2-nistp384", 384),
    ("ecdsa", ["-b", "521"], "ecdsa-sha2-nistp521", 521),
]


_counter = itertools.count()


def pub(tmp_path: Path, key_type: str, extra=(), comment="alice@laptop") -> str:
    """A freshly generated public key line. Never reuses a path."""
    path = tmp_path / f"{key_type}-{next(_counter)}"
    subprocess.run(
        ["ssh-keygen", "-t", key_type, "-N", "", "-C", comment, "-f", str(path), *extra],
        check=True,
        capture_output=True,
    )
    return Path(str(path) + ".pub").read_text().strip()


def sk_key_line(algorithm: str) -> str:
    """A security-key public key line, hand-assembled.

    Generating one needs hardware, but the wire format is fully specified, and
    what is under test is that the platform accepts and preserves it.
    """
    def s(b: bytes) -> bytes:
        return struct.pack(">I", len(b)) + b

    if algorithm == "sk-ssh-ed25519@openssh.com":
        import os

        blob = s(algorithm.encode()) + s(os.urandom(32)) + s(b"ssh:")
    else:
        from cryptography.hazmat.primitives.asymmetric import ec
        from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

        point = (
            ec.generate_private_key(ec.SECP256R1())
            .public_key()
            .public_bytes(Encoding.X962, PublicFormat.UncompressedPoint)
        )
        blob = s(algorithm.encode()) + s(b"nistp256") + s(point) + s(b"ssh:")
    return f"{algorithm} {base64.b64encode(blob).decode()} token@yubikey"


def make_user(session: Session, email: str = "alice@example.com") -> UserORM:
    user = UserORM(email=email)
    session.add(user)
    session.commit()
    session.refresh(user)
    return user


# --- Parsing and validation ------------------------------------------------


@pytest.mark.parametrize("key_type,extra,expected_type,expected_bits", KEY_TYPES)
def test_accepts_every_allowed_type(tmp_path, key_type, extra, expected_type, expected_bits):
    parsed = service.parse_public_key(pub(tmp_path, key_type, tuple(extra)))
    assert parsed.key_type == expected_type
    assert parsed.bits == expected_bits


@pytest.mark.parametrize(
    "algorithm",
    ["sk-ssh-ed25519@openssh.com", "sk-ecdsa-sha2-nistp256@openssh.com"],
)
def test_security_key_variants_are_accepted_and_preserved(algorithm):
    """A hardware-backed key must survive normalization unchanged.

    `load_ssh_public_key` strips the sk-* wrapper and re-serializes as a plain
    key with a different blob, so a normalization that trusted the parser
    would store something that never authenticates.
    """
    line = sk_key_line(algorithm)
    parsed = service.parse_public_key(line)

    assert parsed.key_type == algorithm
    assert parsed.public_key == " ".join(line.split()[:2])
    assert parsed.fingerprint == service.fingerprint_for_blob(
        base64.b64decode(line.split()[1])
    )


@pytest.mark.parametrize("key_type,extra,expected_type,expected_bits", KEY_TYPES)
def test_fingerprint_matches_ssh_keygen(tmp_path, key_type, extra, expected_type, expected_bits):
    path = tmp_path / f"fp-{key_type}-{'-'.join(extra) or 'd'}"
    subprocess.run(
        ["ssh-keygen", "-t", key_type, "-N", "", "-f", str(path), *extra],
        check=True,
        capture_output=True,
    )
    pub_path = Path(str(path) + ".pub")
    reported = subprocess.run(
        ["ssh-keygen", "-lf", str(pub_path)], check=True, capture_output=True, text=True
    ).stdout.split()[1]

    assert service.parse_public_key(pub_path.read_text()).fingerprint == reported


def test_dsa_is_rejected(tmp_path):
    path = tmp_path / "dsa"
    result = subprocess.run(
        ["ssh-keygen", "-t", "dsa", "-N", "", "-f", str(path)], capture_output=True
    )
    if result.returncode != 0:
        pytest.skip("this ssh-keygen refuses to generate DSA keys")
    with pytest.raises(service.SshKeyValidationException) as exc:
        service.parse_public_key(Path(str(path) + ".pub").read_text())
    assert exc.value.code == "unsupported_key_type"


def test_dsa_blob_is_rejected_even_if_ssh_keygen_will_not_make_one():
    """`ssh-dss` is refused by policy; the parser itself would accept it."""
    blob = struct.pack(">I", 7) + b"ssh-dss" + b"\x00" * 32
    line = f"ssh-dss {base64.b64encode(blob).decode()}"
    with pytest.raises(service.SshKeyValidationException) as exc:
        service.parse_public_key(line)
    assert exc.value.code == "unsupported_key_type"


def test_undersized_rsa_is_rejected(tmp_path):
    with pytest.raises(service.SshKeyValidationException) as exc:
        service.parse_public_key(pub(tmp_path, "rsa", ("-b", "1024")))
    assert exc.value.code == "key_too_short"
    assert "2048" in str(exc.value)


def test_prefix_disagreeing_with_blob_is_rejected(tmp_path):
    blob = pub(tmp_path, "ed25519").split()[1]
    with pytest.raises(service.SshKeyValidationException) as exc:
        service.parse_public_key(f"ssh-rsa {blob}")
    assert exc.value.code == "key_type_mismatch"


def test_private_key_is_rejected(tmp_path):
    path = tmp_path / "priv"
    subprocess.run(
        ["ssh-keygen", "-t", "ed25519", "-N", "", "-f", str(path)],
        check=True,
        capture_output=True,
    )
    with pytest.raises(service.SshKeyValidationException) as exc:
        service.parse_public_key(path.read_text())
    assert exc.value.code == "private_key_material"


def test_pem_private_key_is_rejected():
    pem = "-----BEGIN RSA PRIVATE KEY-----\nMIIEow==\n-----END RSA PRIVATE KEY-----"
    with pytest.raises(service.SshKeyValidationException) as exc:
        service.parse_public_key(pem)
    assert exc.value.code == "private_key_material"


def test_multiple_keys_are_rejected(tmp_path):
    """The parser accepts a two-line submission and returns only the first."""
    two = pub(tmp_path, "ed25519") + "\n" + pub(tmp_path, "rsa", ("-b", "2048"))
    with pytest.raises(service.SshKeyValidationException) as exc:
        service.parse_public_key(two)
    assert exc.value.code == "multiple_keys"


@pytest.mark.parametrize(
    "bad",
    ["", "   ", "not a key", "ssh-ed25519", "ssh-ed25519 !!!notbase64!!!", "ssh-ed25519 AAAA"],
)
def test_malformed_submissions_are_rejected(bad):
    with pytest.raises(service.SshKeyValidationException) as exc:
        service.parse_public_key(bad)
    assert exc.value.code in {"malformed_key", "key_type_mismatch"}


def test_parsing_stays_linear_on_adversarial_input():
    """The line is split, not pattern-matched.

    `public_key` is attacker-supplied and unbounded, so parsing must not
    invite backtracking. A pattern here was flagged as polynomial; this pins
    the shape that replaced it.
    """
    import time

    for shape in (
        "ssh-ed25519 " + "A" * 200_000 + "=" * 200_000,
        "a" * 200_000 + " " + "\x00",
        "a A" + " \t" * 100_000 + "\x00",
    ):
        started = time.perf_counter()
        with pytest.raises(service.SshKeyValidationException):
            service.parse_public_key(shape)
        assert time.perf_counter() - started < 2.0


def test_comment_may_contain_spaces(tmp_path):
    """`split(None, 2)` keeps the rest of the line as one comment."""
    type_, blob = pub(tmp_path, "ed25519").split()[:2]
    parsed = service.parse_public_key(f"{type_} {blob} my laptop at home")
    assert parsed.comment == "my laptop at home"


def test_tabs_and_repeated_spaces_are_tolerated(tmp_path):
    type_, blob = pub(tmp_path, "ed25519").split()[:2]
    parsed = service.parse_public_key(f"{type_}\t  {blob}   someone@host")
    assert parsed.key_type == type_
    assert parsed.comment == "someone@host"


def test_every_rejection_code_is_distinct(tmp_path):
    """The codes a client branches on must not collapse onto one another."""
    cases = {
        "private_key_material": "-----BEGIN OPENSSH PRIVATE KEY-----\nx\n-----END OPENSSH PRIVATE KEY-----",
        "multiple_keys": pub(tmp_path, "ed25519") + "\n" + pub(tmp_path, "ed25519", (), "b@c"),
        "key_too_short": pub(tmp_path, "rsa", ("-b", "1024")),
        "key_type_mismatch": "ssh-rsa " + pub(tmp_path, "ed25519").split()[1],
        "malformed_key": "gibberish",
    }
    seen = {}
    for expected, submission in cases.items():
        with pytest.raises(service.SshKeyValidationException) as exc:
            service.parse_public_key(submission)
        seen[expected] = exc.value.code
    assert seen == {k: k for k in cases}


# --- Normalization and labels ---------------------------------------------


def test_comment_is_stripped_from_stored_key(tmp_path):
    line = pub(tmp_path, "ed25519", (), "alice@laptop")
    parsed = service.parse_public_key(line)
    assert parsed.public_key == " ".join(line.split()[:2])
    assert "alice@laptop" not in parsed.public_key


def test_label_defaults_from_comment(tmp_path):
    parsed = service.parse_public_key(pub(tmp_path, "ed25519", (), "alice@laptop"))
    assert service.default_label(parsed) == "alice@laptop"


def test_commentless_key_gets_no_invented_label(tmp_path):
    line = " ".join(pub(tmp_path, "ed25519").split()[:2])
    parsed = service.parse_public_key(line)
    assert service.default_label(parsed) is None


def test_unlabeled_key_stores_reads_and_deletes(db_session, tmp_path):
    """An absent label costs nothing: the fingerprint is the identity."""
    user = make_user(db_session)
    line = " ".join(pub(tmp_path, "ed25519").split()[:2])
    stored = service.add_key(db_session, user_id=user.id, public_key=line)
    assert stored.label is None

    listed = service.list_keys(db_session, user_id=user.id)
    assert [k.label for k in listed] == [None]

    service.delete_key(db_session, user_id=user.id, fingerprint=stored.fingerprint)
    assert service.list_keys(db_session, user_id=user.id) == []


def test_duplicate_message_survives_a_missing_label(db_session, tmp_path):
    user = make_user(db_session)
    line = " ".join(pub(tmp_path, "ed25519").split()[:2])
    service.add_key(db_session, user_id=user.id, public_key=line)
    with pytest.raises(service.DuplicateSshKeyException) as exc:
        service.add_key(db_session, user_id=user.id, public_key=line)
    assert "None" not in str(exc.value)


def test_surrounding_whitespace_is_tolerated(tmp_path):
    line = pub(tmp_path, "ed25519")
    assert (
        service.parse_public_key(f"  \n {line}  \n ").fingerprint
        == service.parse_public_key(line).fingerprint
    )


# --- Storage ---------------------------------------------------------------


def test_add_and_list(db_session, tmp_path):
    user = make_user(db_session)
    service.add_key(db_session, user_id=user.id, public_key=pub(tmp_path, "ed25519"))
    keys = service.list_keys(db_session, user_id=user.id)
    assert len(keys) == 1
    assert keys[0].label == "alice@laptop"
    assert keys[0].key_type == "ssh-ed25519"


def test_explicit_label_wins_over_comment(db_session, tmp_path):
    user = make_user(db_session)
    stored = service.add_key(
        db_session,
        user_id=user.id,
        public_key=pub(tmp_path, "ed25519"),
        label="Work laptop",
    )
    assert stored.label == "Work laptop"


def test_duplicate_is_rejected(db_session, tmp_path):
    user = make_user(db_session)
    line = pub(tmp_path, "ed25519")
    service.add_key(db_session, user_id=user.id, public_key=line)
    with pytest.raises(service.DuplicateSshKeyException):
        service.add_key(db_session, user_id=user.id, public_key=line)
    assert len(service.list_keys(db_session, user_id=user.id)) == 1


def test_comment_difference_does_not_create_a_second_key(db_session, tmp_path):
    user = make_user(db_session)
    line = pub(tmp_path, "ed25519")
    service.add_key(db_session, user_id=user.id, public_key=line)
    type_, blob = line.split()[:2]
    with pytest.raises(service.DuplicateSshKeyException):
        service.add_key(
            db_session, user_id=user.id, public_key=f"{type_} {blob} someone@else"
        )


def test_two_users_may_hold_the_same_key(db_session, tmp_path):
    alice = make_user(db_session, "alice@example.com")
    bob = make_user(db_session, "bob@example.com")
    line = pub(tmp_path, "ed25519")
    service.add_key(db_session, user_id=alice.id, public_key=line)
    service.add_key(db_session, user_id=bob.id, public_key=line)
    assert len(service.list_keys(db_session, user_id=alice.id)) == 1
    assert len(service.list_keys(db_session, user_id=bob.id)) == 1


def test_delete_removes_the_key(db_session, tmp_path):
    user = make_user(db_session)
    stored = service.add_key(db_session, user_id=user.id, public_key=pub(tmp_path, "ed25519"))
    service.delete_key(db_session, user_id=user.id, fingerprint=stored.fingerprint)
    assert service.list_keys(db_session, user_id=user.id) == []


def test_delete_of_unheld_fingerprint_raises(db_session):
    user = make_user(db_session)
    with pytest.raises(NotFoundException):
        service.delete_key(db_session, user_id=user.id, fingerprint="SHA256:nope")


def test_delete_does_not_reach_another_users_key(db_session, tmp_path):
    alice = make_user(db_session, "alice@example.com")
    bob = make_user(db_session, "bob@example.com")
    stored = service.add_key(db_session, user_id=alice.id, public_key=pub(tmp_path, "ed25519"))
    with pytest.raises(NotFoundException):
        service.delete_key(db_session, user_id=bob.id, fingerprint=stored.fingerprint)
    assert len(service.list_keys(db_session, user_id=alice.id)) == 1


def test_no_key_outlives_its_owner(db_session, tmp_path):
    user = make_user(db_session)
    service.add_key(db_session, user_id=user.id, public_key=pub(tmp_path, "ed25519"))
    user_id = user.id

    db_session.execute(text("DELETE FROM \"user\" WHERE id = :id"), {"id": user_id})
    db_session.commit()

    remaining = db_session.execute(
        text("SELECT count(*) FROM user_ssh_key WHERE user_id = :id"), {"id": user_id}
    ).scalar_one()
    assert remaining == 0


def test_deleting_the_account_removes_its_keys(db_session, tmp_path):
    alice = make_user(db_session, "alice@example.com")
    bob = make_user(db_session, "bob@example.com")
    service.add_key(db_session, user_id=alice.id, public_key=pub(tmp_path, "ed25519"))
    service.add_key(db_session, user_id=bob.id, public_key=pub(tmp_path, "ed25519"))

    user_service.delete_user(db_session, user_id=alice.id)

    remaining = db_session.execute(
        text("SELECT count(*) FROM user_ssh_key WHERE user_id = :id"), {"id": alice.id}
    ).scalar_one()
    assert remaining == 0
    assert len(service.list_keys(db_session, user_id=bob.id)) == 1


def test_a_very_large_rsa_key_can_be_stored(db_session):
    """The blob is not itself indexed, so it has no btree row-size ceiling."""
    from cryptography.hazmat.primitives.asymmetric import rsa as _rsa
    from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

    n = (1 << 16383) | (1 << 16382) | 1
    key = _rsa.RSAPublicNumbers(e=65537, n=n).public_key()
    line = key.public_bytes(Encoding.OpenSSH, PublicFormat.OpenSSH).decode()
    assert len(line) > 2704

    user = make_user(db_session)
    stored = service.add_key(db_session, user_id=user.id, public_key=line, label="huge")
    assert stored.bits == 16384
