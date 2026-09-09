"""The certificate store's membership.

Derived from the secrets that exist, written with a version precondition, and
never forcing its way past another manager's field — see
openspec/specs/platform-tls-store/spec.md.
"""

from __future__ import annotations

import json

import pytest
from app.config import CaelusSettings
from app.proc import AdapterCommandError, CommandResult
from app.provisioner import KubeAdapter, Provisioner, ProvisionerError

TLS_NAMESPACE = "caelus-tls"
STORE = "default"


class FakeKubectl:
    """A kubectl that answers `get` from a scripted cluster and records applies."""

    def __init__(self, *, secrets: list[str], store: dict | None) -> None:
        self.secrets = list(secrets)
        self.store = store
        self.applies: list[list[str]] = []
        self.applied_manifests: list[dict] = []
        self.fail_next_apply_with: str | None = None
        self.on_apply = None

    def __call__(self, command: list[str]):
        if command[1] == "get" and command[2] == "secret":
            body = {"items": [{"metadata": {"name": n}} for n in self.secrets]}
            return CommandResult(command=command, returncode=0, stdout=json.dumps(body), stderr="")
        if command[1] == "get" and command[2] == "tlsstore":
            if self.store is None:
                return CommandResult(
                    command=command,
                    returncode=1,
                    stdout="",
                    stderr='Error from server (NotFound): tlsstores.traefik.io "default" not found',
                )
            return CommandResult(
                command=command, returncode=0, stdout=json.dumps(self.store), stderr=""
            )
        if command[1] == "apply":
            self.applies.append(command)
            path = command[command.index("-f") + 1]
            with open(path) as f:
                self.applied_manifests.append(json.load(f))
            if self.on_apply is not None:
                self.on_apply(self)
            if self.fail_next_apply_with is not None:
                message, self.fail_next_apply_with = self.fail_next_apply_with, None
                return CommandResult(command=command, returncode=1, stdout="", stderr=message)
            return CommandResult(command=command, returncode=0, stdout="", stderr="")
        raise AssertionError(f"unexpected command: {command}")


def make_store(*, certificates: list[str] | None, version: str = "100") -> dict:
    spec: dict = {"defaultCertificate": {"secretName": "wildcard-freepod-eu-tls"}}
    if certificates is not None:
        spec["certificates"] = [{"secretName": n} for n in certificates]
    return {
        "apiVersion": "traefik.io/v1alpha1",
        "kind": "TLSStore",
        "metadata": {"name": STORE, "namespace": TLS_NAMESPACE, "resourceVersion": version},
        "spec": spec,
    }


@pytest.fixture(autouse=True)
def _settings(monkeypatch):
    monkeypatch.setattr(
        "app.provisioner.get_settings",
        lambda: CaelusSettings(
            tls_namespace=TLS_NAMESPACE, tls_store_name=STORE, _env_file=None
        ),
    )


def build(*, secrets: list[str], store: dict | None) -> tuple[Provisioner, FakeKubectl]:
    runner = FakeKubectl(secrets=secrets, store=store)
    return Provisioner(kube=KubeAdapter(runner=runner)), runner


def applied_spec(runner: FakeKubectl) -> dict:
    return runner.applied_manifests[-1]["spec"]


def test_membership_is_the_secrets_that_exist():
    provisioner, runner = build(
        secrets=["acct-erik-dev-freepod-eu", "acct-fred-dev-freepod-eu"],
        store=make_store(certificates=[]),
    )

    assert provisioner.reconcile_certificate_store() is True
    assert applied_spec(runner)["certificates"] == [
        {"secretName": "acct-erik-dev-freepod-eu"},
        {"secretName": "acct-fred-dev-freepod-eu"},
    ]


def test_a_requested_but_unissued_certificate_is_not_listed():
    """It has no secret, and naming a missing secret is an error the ingress
    controller reports on every reload."""
    provisioner, runner = build(secrets=[], store=make_store(certificates=[]))

    assert provisioner.reconcile_certificate_store() is False
    assert runner.applied_manifests == []


def test_a_correct_list_is_not_rewritten():
    provisioner, runner = build(
        secrets=["acct-erik-dev-freepod-eu"],
        store=make_store(certificates=["acct-erik-dev-freepod-eu"]),
    )

    assert provisioner.reconcile_certificate_store() is False
    assert runner.applied_manifests == []


def test_an_absent_membership_list_is_written_not_an_obstacle():
    provisioner, runner = build(
        secrets=["acct-erik-dev-freepod-eu"], store=make_store(certificates=None)
    )

    assert provisioner.reconcile_certificate_store() is True
    assert applied_spec(runner)["certificates"] == [{"secretName": "acct-erik-dev-freepod-eu"}]


def test_the_payload_carries_the_version_it_was_computed_against():
    provisioner, runner = build(
        secrets=["acct-erik-dev-freepod-eu"], store=make_store(certificates=[], version="4242")
    )

    provisioner.reconcile_certificate_store()

    assert runner.applied_manifests[-1]["metadata"]["resourceVersion"] == "4242"


def test_the_default_certificate_is_never_in_the_payload():
    """Infrastructure code owns it. A manager that sets it would drop it on its
    next write, leaving connections with no fallback."""
    provisioner, runner = build(
        secrets=["acct-erik-dev-freepod-eu"], store=make_store(certificates=[])
    )

    provisioner.reconcile_certificate_store()

    assert "defaultCertificate" not in applied_spec(runner)
    assert list(applied_spec(runner)) == ["certificates"]


def test_conflicts_are_never_forced():
    provisioner, runner = build(
        secrets=["acct-erik-dev-freepod-eu"], store=make_store(certificates=[])
    )

    provisioner.reconcile_certificate_store()

    for command in runner.applies:
        assert "--force-conflicts" not in command
        assert "--server-side" in command
        assert "--field-manager=caelus-tls" in command


def test_a_stale_write_is_retried_from_a_fresh_read():
    """The version precondition is what makes two workers safe: the loser reads
    again and recomputes rather than dropping the winner's entry."""
    provisioner, runner = build(
        secrets=["acct-erik-dev-freepod-eu"], store=make_store(certificates=[], version="1")
    )

    def other_worker_wins(rn: FakeKubectl) -> None:
        rn.secrets.append("acct-fred-dev-freepod-eu")
        rn.store = make_store(certificates=["acct-fred-dev-freepod-eu"], version="2")
        rn.on_apply = None

    runner.on_apply = other_worker_wins
    runner.fail_next_apply_with = (
        'Operation cannot be fulfilled on tlsstores.traefik.io "default": '
        "the object has been modified; please apply your changes to the latest version"
    )

    assert provisioner.reconcile_certificate_store() is True
    assert applied_spec(runner)["certificates"] == [
        {"secretName": "acct-erik-dev-freepod-eu"},
        {"secretName": "acct-fred-dev-freepod-eu"},
    ]
    assert runner.applied_manifests[-1]["metadata"]["resourceVersion"] == "2"


def test_an_ownership_conflict_is_raised_not_retried():
    """Only a stale version is a retry. A conflict means another manager owns
    the field, and the way past it is the flag this must never pass."""
    provisioner, runner = build(
        secrets=["acct-erik-dev-freepod-eu"], store=make_store(certificates=[])
    )
    runner.fail_next_apply_with = (
        'Apply failed with 1 conflict: conflict with "Terraform": .spec.certificates'
    )

    with pytest.raises(AdapterCommandError):
        provisioner.reconcile_certificate_store()
    assert len(runner.applied_manifests) == 1


def test_it_refuses_to_create_a_store_that_does_not_exist():
    """One it created would carry no default certificate."""
    provisioner, runner = build(secrets=["acct-erik-dev-freepod-eu"], store=None)

    with pytest.raises(ProvisionerError) as exc:
        provisioner.reconcile_certificate_store()
    assert "infrastructure code" in str(exc.value)
    assert runner.applied_manifests == []


def test_drift_is_corrected_by_unrelated_work():
    """Membership is derived from the whole namespace, so any reconcile that
    writes brings it to the complete set — no periodic sweep needed."""
    provisioner, runner = build(
        secrets=["acct-erik-dev-freepod-eu", "acct-fred-dev-freepod-eu"],
        store=make_store(certificates=["acct-erik-dev-freepod-eu"]),
    )

    assert provisioner.reconcile_certificate_store() is True
    assert applied_spec(runner)["certificates"] == [
        {"secretName": "acct-erik-dev-freepod-eu"},
        {"secretName": "acct-fred-dev-freepod-eu"},
    ]


def test_a_removed_certificate_leaves_the_list():
    provisioner, runner = build(
        secrets=["acct-erik-dev-freepod-eu"],
        store=make_store(certificates=["acct-erik-dev-freepod-eu", "acct-gone-dev-freepod-eu"]),
    )

    assert provisioner.reconcile_certificate_store() is True
    assert applied_spec(runner)["certificates"] == [{"secretName": "acct-erik-dev-freepod-eu"}]


def test_the_selector_names_the_platform_label(monkeypatch):
    seen: list[list[str]] = []

    def runner(command):
        seen.append(command)
        return CommandResult(command=command, returncode=0, stdout='{"items": []}', stderr="")

    Provisioner(kube=KubeAdapter(runner=runner)).list_account_certificate_secrets()

    assert "-l" in seen[0]
    assert seen[0][seen[0].index("-l") + 1] == "caelus.dev/component=account-tls"
    assert seen[0][seen[0].index("-n") + 1] == TLS_NAMESPACE
