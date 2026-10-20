from __future__ import annotations

from dataclasses import dataclass
import json
import logging
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any

from app import post_render
from app.config import get_settings
from app.network_policy import TENANT_NAMESPACE_LABELS, tenant_network_policies
from app.proc import AdapterCommandError, CommandRunner, run_command

logger = logging.getLogger(__name__)

@dataclass(frozen=True)
class NamespaceResult:
    name: str
    exists: bool
    changed: bool


class KubeAdapter:
    """Adapter for namespace lifecycle operations."""

    def __init__(self, *, runner: CommandRunner | None = None) -> None:
        self._runner = runner

    def ensure_namespace(self, name: str) -> NamespaceResult:
        logger.info("Ensuring Kubernetes namespace exists: %s", name)
        if self.namespace_exists(name):
            logger.debug("Namespace already exists: %s", name)
            return NamespaceResult(name=name, exists=True, changed=False)

        run_command(
            ["kubectl", "create", "namespace", name],
            runner=self._runner,
            error_message=f"Failed to create namespace {name}",
        )
        logger.info("Created namespace: %s", name)
        return NamespaceResult(name=name, exists=True, changed=True)

    def delete_namespace(self, name: str) -> NamespaceResult:
        logger.info("Deleting Kubernetes namespace: %s", name)
        try:
            run_command(
                ["kubectl", "delete", "namespace", name, "--ignore-not-found=true"],
                runner=self._runner,
                error_message=f"Failed to delete namespace {name}",
            )
            logger.info("Deleted namespace: %s", name)
            return NamespaceResult(name=name, exists=False, changed=True)
        except AdapterCommandError as exc:
            if "not found" in exc.result.stderr.lower():
                logger.debug("Namespace was already absent: %s", name)
                return NamespaceResult(name=name, exists=False, changed=False)
            raise

    def namespace_exists(self, name: str) -> bool:
        try:
            run_command(
                ["kubectl", "get", "namespace", name, "-o", "name"],
                runner=self._runner,
                error_message=f"Failed to check namespace {name}",
            )
            logger.debug("Namespace exists: %s", name)
            return True
        except AdapterCommandError as exc:
            text = f"{exc.result.stderr}\n{exc.result.stdout}".lower()
            if "not found" in text:
                logger.debug("Namespace not found: %s", name)
                return False
            raise

    def label_namespace(self, name: str, labels: dict[str, str]) -> None:
        logger.info("Labeling namespace %s: %s", name, labels)
        pairs = [f"{key}={value}" for key, value in labels.items()]
        run_command(
            ["kubectl", "label", "namespace", name, *pairs, "--overwrite"],
            runner=self._runner,
            error_message=f"Failed to label namespace {name}",
        )

    def object_exists_by_label(self, *, kind: str, namespace: str, selector: str) -> bool:
        """Whether any object of ``kind`` in ``namespace`` matches ``selector``."""
        try:
            result = run_command(
                ["kubectl", "get", kind, "-n", namespace, "-l", selector, "-o", "json"],
                runner=self._runner,
                error_message=f"Failed to look up {kind} objects in namespace {namespace}",
            )
        except AdapterCommandError as exc:
            text = f"{exc.result.stderr}\n{exc.result.stdout}".lower()
            if "not found" in text:
                return False
            raise

        return bool(json.loads(result.stdout).get("items", []))

    def list_object_names(self, *, kind: str, namespace: str, selector: str) -> list[str]:
        """Names of the objects of ``kind`` in ``namespace`` matching ``selector``.

        Matching nothing is success (empty list).
        """
        result = run_command(
            ["kubectl", "get", kind, "-n", namespace, "-l", selector, "-o", "json"],
            runner=self._runner,
            error_message=f"Failed to list {kind} matching {selector} in namespace {namespace}",
        )
        items = json.loads(result.stdout).get("items", [])
        return [item["metadata"]["name"] for item in items]

    def upsert_secret(
        self,
        *,
        namespace: str,
        name: str,
        string_data: dict[str, str],
        labels: dict[str, str],
        secret_type: str = "Opaque",
    ) -> None:
        """Declaratively upsert a Secret, Opaque unless ``secret_type`` says otherwise.

        ``stringData`` rather than ``data`` so nothing here has to base64 the
        values; the API server does it. Keyed on (namespace, name), so a stable
        name means in-place update and a re-reconcile rewrites the same object
        rather than churning it.

        The values are credentials, so they are handed to ``kubectl`` through a
        temporary file that ``apply_manifest`` deletes rather than through argv,
        where they would be visible to any process listing on the node.
        """
        self.apply_manifest(
            {
                "apiVersion": "v1",
                "kind": "Secret",
                "type": secret_type,
                "metadata": {"name": name, "namespace": namespace, "labels": labels},
                "stringData": string_data,
            },
            error_message=f"Failed to apply Secret {namespace}/{name}",
        )

    def delete_secrets_by_label(
        self, *, namespace: str, selector: str, except_name: str | None = None
    ) -> None:
        """Delete every Secret matching ``selector``, optionally sparing one.

        Matching nothing is success.
        """
        cmd = [
            "kubectl", "delete", "secret",
            "-n", namespace,
            "-l", selector,
            "--ignore-not-found",
        ]
        if except_name is not None:
            cmd += ["--field-selector", f"metadata.name!={except_name}"]
        run_command(
            cmd,
            runner=self._runner,
            error_message=(
                f"Failed to delete Secrets matching {selector} in namespace {namespace}"
            ),
        )

    def apply_manifest(self, manifest: dict[str, Any], *, error_message: str) -> None:
        """Declaratively upsert a single manifest via ``kubectl apply``.

        Idempotent by construction, so retries and fleet-wide re-applies are
        no-ops when nothing changed; keyed on (kind, namespace, name), so a stable
        name means in-place update rather than churn.
        """
        with NamedTemporaryFile(mode="w", encoding="utf-8", suffix=".json") as f:
            json.dump(manifest, f)
            f.flush()
            run_command(
                ["kubectl", "apply", "-f", f.name],
                runner=self._runner,
                error_message=error_message,
            )

    def delete_object(self, *, kind: str, namespace: str, name: str, error_message: str) -> None:
        """Delete one object by name; matching nothing is success.

        Idempotent, so reconcile can call it unconditionally to converge a
        namespace that should not hold the object.
        """
        run_command(
            ["kubectl", "delete", kind, name, "-n", namespace, "--ignore-not-found"],
            runner=self._runner,
            error_message=error_message,
        )


@dataclass(frozen=True)
class HelmReleaseOperationResult:
    release_name: str
    namespace: str
    changed: bool
    status: str | None = None
    revision: int | None = None


@dataclass(frozen=True)
class HelmReleaseStatusResult:
    release_name: str
    namespace: str
    exists: bool
    status: str | None = None
    revision: int | None = None
    raw: dict[str, Any] | None = None


class HelmAdapter:
    """Adapter for Helm release lifecycle operations."""

    def __init__(self, *, runner: CommandRunner | None = None) -> None:
        self._runner = runner

    def helm_upgrade_install(
        self,
        *,
        release_name: str,
        namespace: str,
        chart_ref: str,
        chart_version: str,
        chart_digest: str | None,
        values: dict[str, Any],
        timeout: int,
        atomic: bool,
        wait: bool,
        hostname: str | None = None,
    ) -> HelmReleaseOperationResult:
        logger.info(
            "Applying Helm release '%s' in namespace '%s' (chart=%s version=%s digest=%s)",
            release_name,
            namespace,
            chart_ref,
            chart_version,
            chart_digest,
        )
        resolved_chart = _with_optional_digest(chart_ref=chart_ref, chart_digest=chart_digest)
        with NamedTemporaryFile(mode="w", encoding="utf-8", suffix=".json") as f:
            f.write(json.dumps(values, indent=2))
            f.flush()

            cmd = [
                "helm",
                "upgrade",
                "--install", release_name, resolved_chart,
                "--namespace", namespace,
                "--timeout", f"{timeout}s",
                "-f", f.name,
            ]
            if not chart_digest:
                cmd.extend(["--version", chart_version])
            settings = get_settings()
            cmd.extend([
                "--post-renderer", post_render.PLUGIN_NAME,
                "--post-renderer-args", f"--image={settings.egress_gate_image}",
                "--post-renderer-args",
                f"--deadline-seconds={settings.egress_gate_deadline_seconds}",
            ])
            if hostname:
                cmd.extend(["--post-renderer-args", f"--hostname={hostname}"])
            if atomic:
                cmd.append("--atomic")
            if wait:
                cmd.append("--wait")

            logger.info(f"Helm values for deployment {namespace}/{release_name}:\n{json.dumps(values, indent=2)}")
            run_command(
                cmd,
                runner=self._runner,
                error_message=f"Failed to upgrade/install release {release_name}",
            )

        status = self.helm_get_release_status(release_name=release_name, namespace=namespace)
        return HelmReleaseOperationResult(
            release_name=release_name,
            namespace=namespace,
            changed=True,
            status=status.status,
            revision=status.revision,
        )

    def helm_uninstall(
        self,
        *,
        release_name: str,
        namespace: str,
        timeout: int,
        wait: bool,
    ) -> HelmReleaseOperationResult:
        logger.info("Uninstalling Helm release '%s' from namespace '%s'", release_name, namespace)
        cmd = [
            "helm",
            "uninstall",
            release_name,
            "--namespace",
            namespace,
            "--timeout",
            f"{timeout}s",
        ]
        if wait:
            cmd.append("--wait")
        try:
            run_command(
                cmd,
                runner=self._runner,
                error_message=f"Failed to uninstall release {release_name}",
            )
            return HelmReleaseOperationResult(
                release_name=release_name,
                namespace=namespace,
                changed=True,
                status="uninstalled",
            )
        except AdapterCommandError as exc:
            text = f"{exc.result.stderr}\n{exc.result.stdout}".lower()
            if "release: not found" in text or "not found" in text:
                logger.debug(
                    "Helm release already absent: release='%s' namespace='%s'",
                    release_name,
                    namespace,
                )
                return HelmReleaseOperationResult(
                    release_name=release_name,
                    namespace=namespace,
                    changed=False,
                    status="not-found",
                )
            raise

    def helm_get_release_status(self, *, release_name: str, namespace: str) -> HelmReleaseStatusResult:
        logger.debug(
            "Fetching Helm release status: release='%s' namespace='%s'",
            release_name,
            namespace,
        )
        try:
            result = run_command(
                ["helm", "status", release_name, "--namespace", namespace, "--output", "json"],
                runner=self._runner,
                error_message=f"Failed to fetch release status for {release_name}",
            )
        except AdapterCommandError as exc:
            text = f"{exc.result.stderr}\n{exc.result.stdout}".lower()
            if "release: not found" in text or "not found" in text:
                logger.debug(
                    "Helm release not found during status check: release='%s' namespace='%s'",
                    release_name,
                    namespace,
                )
                return HelmReleaseStatusResult(release_name=release_name, namespace=namespace, exists=False)
            raise

        try:
            payload = json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid JSON from helm status for release {release_name}") from exc

        info = payload.get("info", {}) if isinstance(payload, dict) else {}
        status = info.get("status") if isinstance(info, dict) else None
        revision = payload.get("version") if isinstance(payload, dict) else None
        if not isinstance(revision, int):
            revision = None

        return HelmReleaseStatusResult(
            release_name=release_name,
            namespace=namespace,
            exists=True,
            status=status if isinstance(status, str) else None,
            revision=revision,
            raw=payload if isinstance(payload, dict) else None,
        )


def _with_optional_digest(*, chart_ref: str, chart_digest: str | None) -> str:
    if not chart_digest or "@" in chart_ref:
        return chart_ref
    return f"{chart_ref}@{chart_digest}"


def _flatten_values(
    values: dict[str, Any], prefix: str = ""
) -> list[tuple[str, str]]:
    """Flatten a nested dict into Helm --set compatible (key, value) pairs.

    Uses dot-notation for nested dicts and bracket-indexing for lists,
    matching Helm's --set parsing rules.
    """
    items: list[tuple[str, str]] = []
    for k, v in values.items():
        key = f"{prefix}{k}" if not prefix else f"{prefix}.{k}"
        if isinstance(v, dict):
            items.extend(_flatten_values(v, prefix=key))
        elif isinstance(v, list):
            for i, elem in enumerate(v):
                indexed = f"{key}[{i}]"
                if isinstance(elem, dict):
                    items.extend(_flatten_values(elem, prefix=indexed))
                else:
                    items.append((indexed, str(elem)))
        elif isinstance(v, bool):
            items.append((key, str(v).lower()))
        elif v is None:
            items.append((key, "null"))
        else:
            items.append((key, str(v)))
    return items


class _values_file:
    def __init__(self, values: dict[str, Any]) -> None:
        self._values = values
        self._tmp: NamedTemporaryFile[str] | None = None
        self.path: Path | None = None

    def __enter__(self) -> Path:
        tmp = NamedTemporaryFile(mode="w", encoding="utf-8", suffix=".json", delete=False)
        tmp.write(json.dumps(self._values))
        tmp.flush()
        tmp.close()
        self._tmp = tmp
        self.path = Path(tmp.name)
        logger.debug("Wrote temporary values file: %s", self.path)
        return self.path

    def __exit__(self, exc_type, exc, tb) -> None:
        if self.path and self.path.exists():
            self.path.unlink()
            logger.debug("Removed temporary values file: %s", self.path)


class Provisioner:
    """Facade over Kubernetes/Helm adapters used by reconcile logic."""

    def __init__(self, *, kube: KubeAdapter | None = None, helm: HelmAdapter | None = None) -> None:
        self.kube = kube or KubeAdapter()
        self.helm = helm or HelmAdapter()

    # TODO: these namespace functions should not be exposed -- namespace creation/deletion should be done by the install/uninstall methods transparently
    def ensure_namespace(self, *, name: str) -> NamespaceResult:
        return self.kube.ensure_namespace(name)

    def build_tenant_policies(
        self, *, namespace: str, system_values_json: dict[str, Any] | None
    ) -> list[dict[str, Any]]:
        """Render (without applying) every NetworkPolicy the deployment in this
        namespace should hold, tailored to its product's system values."""
        return tenant_network_policies(
            namespace=namespace, system_values_json=system_values_json, settings=get_settings()
        )

    def ensure_tenant_network_policies(
        self,
        *,
        namespace: str,
        labels: dict[str, str] | None,
        system_values_json: dict[str, Any] | None,
    ) -> None:
        """Apply the platform-owned isolation guardrails to a tenant namespace.

        Labels the namespace for Pod Security Admission + tenant selection, then
        reconciles its NetworkPolicy set to exactly what the product needs:
        applies every rendered policy and removes any platform-managed policy no
        longer wanted (e.g. the mailer overlay after a product drops the relay).
        Idempotent and decoupled from Helm -- called before Helm installs anything
        so no workload runs un-jailed, and re-run cheaply for drift/fleet updates.

        Callers hand over the raw inputs and own none of the policy logic, so
        reconcile and ``sync-network-policies`` cannot drift.
        """
        self.kube.label_namespace(namespace, labels or TENANT_NAMESPACE_LABELS)
        desired = self.build_tenant_policies(
            namespace=namespace, system_values_json=system_values_json
        )
        desired_names = {policy["metadata"]["name"] for policy in desired}
        for policy in desired:
            name = policy["metadata"]["name"]
            self.kube.apply_manifest(
                policy,
                error_message=f"Failed to apply NetworkPolicy {name} in namespace {namespace}",
            )
        # Converge: remove any platform-managed policy that should no longer be
        # present. Generic on purpose -- no policy's purpose is named here.
        for name in self.kube.list_object_names(
            kind="networkpolicy",
            namespace=namespace,
            selector="app.kubernetes.io/managed-by=caelus",
        ):
            if name not in desired_names:
                self.kube.delete_object(
                    kind="networkpolicy",
                    namespace=namespace,
                    name=name,
                    error_message=f"Failed to remove NetworkPolicy {name} in namespace {namespace}",
                )

    def delete_namespace(self, *, name: str) -> NamespaceResult:
        return self.kube.delete_namespace(name)

    def namespace_exists(self, *, name: str) -> bool:
        return self.kube.namespace_exists(name)

    SSH_ACCESS_KIND = "service"

    def ssh_access_exists(self, *, namespace: str, instance: str) -> bool:
        """Whether this deployment offers SSH access at all."""
        return self.kube.object_exists_by_label(
            kind=self.SSH_ACCESS_KIND,
            namespace=namespace,
            selector=self.ssh_access_selector(instance),
        )

    @staticmethod
    def ssh_access_selector(instance: str) -> str:
        return f"caelus.dev/component=ssh,app.kubernetes.io/instance={instance}"

    def upsert_secret(
        self,
        *,
        namespace: str,
        name: str,
        string_data: dict[str, str],
        labels: dict[str, str],
        secret_type: str = "Opaque",
    ) -> None:
        """Upsert a platform-owned Secret into a deployment's namespace."""
        self.kube.upsert_secret(
            namespace=namespace,
            name=name,
            string_data=string_data,
            labels=labels,
            secret_type=secret_type,
        )

    def delete_secrets_by_label(
        self, *, namespace: str, selector: str, except_name: str | None = None
    ) -> None:
        """Remove platform-owned Secrets a deployment no longer references."""
        self.kube.delete_secrets_by_label(
            namespace=namespace, selector=selector, except_name=except_name
        )

    def helm_upgrade_install(
        self,
        *,
        release_name: str,
        namespace: str,
        chart_ref: str,
        chart_version: str,
        chart_digest: str | None,
        values: dict[str, Any],
        timeout: int,
        atomic: bool,
        wait: bool,
        hostname: str | None = None,
    ) -> HelmReleaseOperationResult:
        return self.helm.helm_upgrade_install(
            release_name=release_name,
            namespace=namespace,
            chart_ref=chart_ref,
            chart_version=chart_version,
            chart_digest=chart_digest,
            values=values,
            timeout=timeout,
            atomic=atomic,
            wait=wait,
            hostname=hostname,
        )

    def helm_uninstall(
        self,
        *,
        release_name: str,
        namespace: str,
        timeout: int,
        wait: bool,
    ) -> HelmReleaseOperationResult:
        return self.helm.helm_uninstall(
            release_name=release_name,
            namespace=namespace,
            timeout=timeout,
            wait=wait,
        )

    def helm_get_release_status(
        self,
        *,
        release_name: str,
        namespace: str,
    ) -> HelmReleaseStatusResult:
        return self.helm.helm_get_release_status(release_name=release_name, namespace=namespace)


provisioner = Provisioner()
