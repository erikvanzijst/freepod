from __future__ import annotations

import json
import subprocess

import pytest

from app.proc import AdapterCommandError
from app.provisioner import HelmAdapter, KubeAdapter


def _result(*, args: list[str], returncode: int, stdout: str = "", stderr: str = "") -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(args=args, returncode=returncode, stdout=stdout, stderr=stderr)


def test_kube_ensure_namespace_creates_when_missing() -> None:
    calls: list[list[str]] = []

    def runner(cmd: list[str]) -> subprocess.CompletedProcess[str]:
        calls.append(cmd)
        if cmd[:4] == ["kubectl", "get", "namespace", "ns-a"]:
            return _result(args=cmd, returncode=1, stderr="Error from server (NotFound): namespaces \"ns-a\" not found")
        if cmd[:4] == ["kubectl", "create", "namespace", "ns-a"]:
            return _result(args=cmd, returncode=0, stdout="namespace/ns-a created")
        raise AssertionError(f"unexpected command: {cmd}")

    adapter = KubeAdapter(runner=runner)
    out = adapter.ensure_namespace("ns-a")

    assert out.exists is True
    assert out.changed is True
    assert calls[0][:4] == ["kubectl", "get", "namespace", "ns-a"]
    assert calls[1][:4] == ["kubectl", "create", "namespace", "ns-a"]


def test_kube_namespace_exists_bubbles_non_not_found_errors_as_classified() -> None:
    def runner(cmd: list[str]) -> subprocess.CompletedProcess[str]:
        return _result(args=cmd, returncode=1, stderr="Unable to connect to the server: i/o timeout")

    adapter = KubeAdapter(runner=runner)
    with pytest.raises(AdapterCommandError) as exc_info:
        adapter.namespace_exists("ns-a")
    assert "i/o timeout" in str(exc_info.value).lower()


def test_helm_upgrade_install_passes_values_and_returns_status() -> None:
    calls: list[list[str]] = []

    def runner(cmd: list[str]) -> subprocess.CompletedProcess[str]:
        calls.append(cmd)
        if cmd[:3] == ["helm", "upgrade", "--install"]:
            return _result(args=cmd, returncode=0, stdout="Release upgraded")
        if cmd[:2] == ["helm", "status"]:
            payload = {"info": {"status": "deployed"}, "version": 7}
            return _result(args=cmd, returncode=0, stdout=json.dumps(payload))
        raise AssertionError(f"unexpected command: {cmd}")

    adapter = HelmAdapter(runner=runner)
    out = adapter.helm_upgrade_install(
        release_name="rel-a",
        namespace="ns-a",
        chart_ref="oci://example/chart",
        chart_version="1.2.3",
        chart_digest="sha256:abc",
        values={"user": {"message": "hello"}},
        timeout=300,
        atomic=True,
        wait=True,
    )

    assert out.changed is True
    assert out.status == "deployed"
    assert out.revision == 7
    upgrade_cmd = calls[0]
    assert "--set" not in upgrade_cmd
    assert "-f" in upgrade_cmd
    assert "oci://example/chart@sha256:abc" in upgrade_cmd
    assert "--version" not in upgrade_cmd
    assert "--atomic" in upgrade_cmd
    assert "--wait" in upgrade_cmd
    assert "--plain-http" not in upgrade_cmd
    assert "--insecure-skip-tls-verify" not in upgrade_cmd


def test_helm_status_not_found_returns_exists_false() -> None:
    def runner(cmd: list[str]) -> subprocess.CompletedProcess[str]:
        return _result(args=cmd, returncode=1, stderr="Error: release: not found")

    adapter = HelmAdapter(runner=runner)
    out = adapter.helm_get_release_status(release_name="rel-a", namespace="ns-a")
    assert out.exists is False
    assert out.status is None


def test_helm_uninstall_not_found_is_idempotent() -> None:
    def runner(cmd: list[str]) -> subprocess.CompletedProcess[str]:
        return _result(args=cmd, returncode=1, stderr="Error: uninstall: Release not loaded: rel-a: release: not found")

    adapter = HelmAdapter(runner=runner)
    out = adapter.helm_uninstall(release_name="rel-a", namespace="ns-a", timeout=120, wait=True)
    assert out.changed is False
    assert out.status == "not-found"


def test_helm_upgrade_install_timeout_raises_command_error() -> None:
    def runner(cmd: list[str]) -> subprocess.CompletedProcess[str]:
        return _result(args=cmd, returncode=1, stderr="UPGRADE FAILED: context deadline exceeded")

    adapter = HelmAdapter(runner=runner)
    with pytest.raises(AdapterCommandError) as exc_info:
        adapter.helm_upgrade_install(
            release_name="rel-a",
            namespace="ns-a",
            chart_ref="oci://example/chart",
            chart_version="1.2.3",
            chart_digest=None,
            values={},
            timeout=300,
            atomic=False,
            wait=False,
        )
    assert "context deadline exceeded" in str(exc_info.value).lower()


def test_kube_label_namespace_overwrites() -> None:
    calls: list[list[str]] = []

    def runner(cmd: list[str]) -> subprocess.CompletedProcess[str]:
        calls.append(cmd)
        return _result(args=cmd, returncode=0, stdout="namespace/ns-a labeled")

    adapter = KubeAdapter(runner=runner)
    adapter.label_namespace("ns-a", {"caelus.dev/tenant": "true", "k": "v"})

    assert calls[0][:3] == ["kubectl", "label", "namespace"]
    assert "caelus.dev/tenant=true" in calls[0]
    assert "k=v" in calls[0]
    assert "--overwrite" in calls[0]


def test_kube_apply_manifest_writes_json_and_applies() -> None:
    applied: list[dict] = []

    def runner(cmd: list[str]) -> subprocess.CompletedProcess[str]:
        assert cmd[:3] == ["kubectl", "apply", "-f"]
        with open(cmd[3], encoding="utf-8") as fh:
            applied.append(json.load(fh))
        return _result(args=cmd, returncode=0, stdout="configured")

    adapter = KubeAdapter(runner=runner)
    adapter.apply_manifest({"kind": "NetworkPolicy", "metadata": {"name": "x"}}, error_message="boom")

    assert applied == [{"kind": "NetworkPolicy", "metadata": {"name": "x"}}]


def test_kube_apply_manifest_raises_on_failure() -> None:
    def runner(cmd: list[str]) -> subprocess.CompletedProcess[str]:
        return _result(args=cmd, returncode=1, stderr="the server could not find the requested resource")

    adapter = KubeAdapter(runner=runner)
    with pytest.raises(AdapterCommandError) as exc_info:
        adapter.apply_manifest({"kind": "NetworkPolicy"}, error_message="apply failed")
    assert "apply failed" in str(exc_info.value)
