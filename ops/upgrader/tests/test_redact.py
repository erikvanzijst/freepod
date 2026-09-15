import base64
import json

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from upgrader.redact import Redactor

PEM = (
    rsa.generate_private_key(public_exponent=65537, key_size=2048)
    .private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.TraditionalOpenSSL,
        serialization.NoEncryption(),
    )
    .decode()
)
KEY_B64 = base64.b64encode(PEM.encode()).decode()


def redactor():
    r = Redactor({"INFERENCE_API_KEY": "sk-inference-123", "DASHBOARD_PASSWORD": "hunter2hunter2"}, KEY_B64)
    r.add_token("ghs_first111")
    r.add_token("ghs_second22")
    return r


def test_each_secret():
    r = redactor()
    assert r("key sk-inference-123") == "key [redacted:INFERENCE_API_KEY]"
    assert r("pw hunter2hunter2") == "pw [redacted:DASHBOARD_PASSWORD]"
    assert r(f"export GITHUB_APP_PRIVATE_KEY={KEY_B64}") == (
        "export GITHUB_APP_PRIVATE_KEY=[redacted:GITHUB_APP_PRIVATE_KEY]"
    )


def test_every_minted_token():
    assert redactor()("a ghs_first111 b ghs_second22") == (
        "a [redacted:github-token] b [redacted:github-token]"
    )


def test_decoded_key_and_a_single_line_of_it():
    r = redactor()
    assert PEM.strip() not in r(f"cat key.pem\n{PEM}")
    line = PEM.splitlines()[5]
    assert r(f"head: {line}") == "head: [redacted:GITHUB_APP_PRIVATE_KEY]"


def test_key_inside_a_json_string():
    transcript = json.dumps({"content": [{"type": "text", "text": PEM}]})
    out = redactor()(transcript)
    assert all(line not in out for line in PEM.splitlines()[1:-1])
    json.loads(out)


def test_repeated_occurrences():
    assert redactor()("sk-inference-123 sk-inference-123") == (
        "[redacted:INFERENCE_API_KEY] [redacted:INFERENCE_API_KEY]"
    )


def test_token_inside_a_json_string():
    line = json.dumps({"text": "GH_TOKEN=ghs_first111\n"})
    assert "ghs_first111" not in redactor()(line)


def test_unset_or_empty_secret_changes_nothing():
    r = Redactor({"INFERENCE_API_KEY": "", "DASHBOARD_PASSWORD": None}, None)
    r.add_token("")
    text = "nothing to see: , '' and so on"
    assert r(text) == text


def test_bytes_that_are_not_utf8():
    assert Redactor({"X": "secret"}).bytes(b"\xff secret \xfe") == b"\xff [redacted:X] \xfe"
