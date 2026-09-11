from __future__ import annotations

from dataclasses import dataclass
import json
import logging
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any

from app.config import get_settings
from app.network_policy import TENANT_NAMESPACE_LABELS, build_tenant_baseline_policy
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

    def get_object(self, *, kind: str, namespace: str, name: str) -> dict[str, Any] | None:
        """Read one object, or ``None`` when it is not there."""
        try:
            result = run_command(
                ["kubectl", "get", kind, name, "-n", namespace, "-o", "json"],
                runner=self._runner,
                error_message=f"Failed to read {kind}/{name} in namespace {namespace}",
            )
        except AdapterCommandError as exc:
            text = f"{exc.result.stderr}\n{exc.result.stdout}".lower()
            if "not found" in text:
                return None
            raise
        return json.loads(result.stdout)

    def list_secret_names(self, *, namespace: str, selector: str) -> list[str]:
        """Names of the Secrets in ``namespace`` matching ``selector``."""
        result = run_command(
            ["kubectl", "get", "secret", "-n", namespace, "-l", selector, "-o", "json"],
            runner=self._runner,
            error_message=f"Failed to list Secrets matching {selector} in namespace {namespace}",
        )
        items = json.loads(result.stdout).get("items", [])
        return [item["metadata"]["name"] for item in items]

    def server_side_apply(self, manifest: dict[str, Any], *, field_manager: str) -> None:
        """Apply the fields in *manifest* as *field_manager*, and no others.

        `--force-conflicts` is deliberately absent and must stay absent. It is
        what the tooling offers to get past a conflict, and taking it would let
        this manager own a field another actor set -- then drop that field on
        its next write, which for `defaultCertificate` means connections with no
        fallback certificate.

        A `metadata.resourceVersion` in the manifest makes the write conditional
        on the object not having changed since it was read.
        """
        with NamedTemporaryFile(mode="w", encoding="utf-8", suffix=".json") as f:
            json.dump(manifest, f)
            f.flush()
            run_command(
                [
                    "kubectl",
                    "apply",
                    "--server-side",
                    f"--field-manager={field_manager}",
                    "-f",
                    f.name,
                ],
                runner=self._runner,
                error_message=(
                    f"Failed to apply {manifest['kind']}/{manifest['metadata']['name']} "
                    f"as {field_manager}"
                ),
            )

    def upsert_secret(
        self, *, namespace: str, name: str, string_data: dict[str, str], labels: dict[str, str]
    ) -> None:
        """Declaratively upsert an Opaque Secret.

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
                "type": "Opaque",
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


STORE_FIELD_MANAGER = "caelus-tls"
STORE_WRITE_ATTEMPTS = 5


class ProvisionerError(Exception):
    """The cluster is not in a state this can act on."""


def _is_stale_write(exc: AdapterCommandError) -> bool:
    """Whether a rejected apply was the version precondition, not an ownership conflict."""
    text = f"{exc.result.stderr}\n{exc.result.stdout}".lower()
    return "the object has been modified" in text


class Provisioner:
    """Facade over Kubernetes/Helm adapters used by reconcile logic."""

    def __init__(self, *, kube: KubeAdapter | None = None, helm: HelmAdapter | None = None) -> None:
        self.kube = kube or KubeAdapter()
        self.helm = helm or HelmAdapter()

    # TODO: these namespace functions should not be exposed -- namespace creation/deletion should be done by the install/uninstall methods transparently
    def ensure_namespace(self, *, name: str) -> NamespaceResult:
        return self.kube.ensure_namespace(name)

    def build_tenant_policy(self, *, namespace: str) -> dict[str, Any]:
        """Render (without applying) the baseline NetworkPolicy for a namespace."""
        return build_tenant_baseline_policy(namespace=namespace, settings=get_settings())

    def ensure_tenant_isolation(self, *, namespace: str) -> None:
        """Apply the platform-owned isolation guardrails to a tenant namespace.

        Idempotent and decoupled from the Helm release: labels the namespace for
        Pod Security Admission + tenant selection, then applies the baseline
        NetworkPolicy. Called before Helm installs anything so no workload ever
        runs un-jailed, and re-run cheaply for drift/fleet updates without
        touching Helm.
        """
        self.kube.label_namespace(namespace, TENANT_NAMESPACE_LABELS)
        self.kube.apply_manifest(
            self.build_tenant_policy(namespace=namespace),
            error_message=f"Failed to apply baseline NetworkPolicy in namespace {namespace}",
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

    ACCOUNT_CERT_LABEL = "caelus.dev/component"
    ACCOUNT_CERT_LABEL_VALUE = "account-tls"

    @staticmethod
    def account_certificate_name(fqdn: str) -> str:
        """The certificate and secret name for an account's own name.

        Derived from the fully qualified name so dev's and production's cannot
        collide -- they share one namespace in one cluster, and `alice` is a
        different person in each (D10).
        """
        return "acct-" + fqdn.replace(".", "-")

    def ensure_account_certificate(self, *, fqdn: str) -> str:
        """Request the certificate covering everything the account deploys.

        Returns the secret name. Idempotent: a stable name means a repeat call
        rewrites the same object, and cert-manager does not reissue for an
        unchanged spec.

        The label goes on `secretTemplate` rather than on the Certificate,
        because cert-manager does not copy a certificate's own labels onto the
        secret it writes -- and the secret is what the store's membership is
        derived from.
        """
        settings = get_settings()
        name = self.account_certificate_name(fqdn)
        self.kube.apply_manifest(
            {
                "apiVersion": "cert-manager.io/v1",
                "kind": "Certificate",
                "metadata": {
                    "name": name,
                    "namespace": settings.tls_namespace,
                    "labels": {self.ACCOUNT_CERT_LABEL: self.ACCOUNT_CERT_LABEL_VALUE},
                },
                "spec": {
                    "secretName": name,
                    "secretTemplate": {
                        "labels": {self.ACCOUNT_CERT_LABEL: self.ACCOUNT_CERT_LABEL_VALUE}
                    },
                    "issuerRef": {
                        "name": settings.account_tls_cluster_issuer,
                        "kind": "ClusterIssuer",
                    },
                    "commonName": f"*.{fqdn}",
                    "dnsNames": [f"*.{fqdn}", fqdn],
                    # Explicit, not the issuer client's RSA default: the ingress
                    # controller re-parses every certificate in its store on each
                    # rebuild, and the secret is a third the size.
                    "privateKey": {"algorithm": "ECDSA", "size": 256},
                },
            },
            error_message=f"Failed to request the account certificate for {fqdn}",
        )
        return name

    def account_certificate_state(self, *, name: str) -> tuple[bool, str | None]:
        """Whether the account's certificate is issued, and why not if it is not.

        The reason is the point: a certificate that will never be issued -- an
        exhausted allowance, a rejected challenge -- says so here, and the
        deployment can fail naming it rather than timing out against a silence.
        """
        settings = get_settings()
        obj = self.kube.get_object(
            kind="certificate", namespace=settings.tls_namespace, name=name
        )
        if obj is None:
            return False, "the certificate has not been created"
        for condition in obj.get("status", {}).get("conditions", []):
            if condition.get("type") == "Ready":
                if condition.get("status") == "True":
                    return True, None
                return False, condition.get("message") or condition.get("reason")
        return False, "issuance has not started"

    def list_account_certificate_secrets(self) -> list[str]:
        """The account certificates that can actually be served.

        Secrets, not `Certificate` objects: a requested certificate that has not
        been issued has no secret, and naming a secret that does not exist is an
        error the ingress controller reports on every reload.
        """
        settings = get_settings()
        return sorted(
            self.kube.list_secret_names(
                namespace=settings.tls_namespace,
                selector=f"{self.ACCOUNT_CERT_LABEL}={self.ACCOUNT_CERT_LABEL_VALUE}",
            )
        )

    def reconcile_certificate_store(self) -> bool:
        """Bring the store's membership to the set of certificates that exist.

        Returns whether it wrote. Derived from the whole namespace rather than
        from one deployment, so any reconcile corrects drift for every account --
        which is what removes the need for a periodic sweep, at the price of a
        read in the common case.

        Compare-and-swap, because recomputing the whole list is not what makes
        concurrent writes safe -- it is the mechanism by which they are lost.
        Two workers computing at different moments and writing whole lists means
        the later drops what the earlier added. The `resourceVersion` read here
        is carried into the write, so a stale one is refused and retried.
        """
        settings = get_settings()
        for _ in range(STORE_WRITE_ATTEMPTS):
            store = self.kube.get_object(
                kind="tlsstore",
                namespace=settings.tls_namespace,
                name=settings.tls_store_name,
            )
            if store is None:
                # Creating one here would produce a store with no default
                # certificate: infrastructure code owns that field, and this
                # manager must never set it.
                raise ProvisionerError(
                    f"No TLSStore/{settings.tls_store_name} in {settings.tls_namespace}; "
                    "it is created by infrastructure code, not here"
                )
            desired = self.list_account_certificate_secrets()
            current = [
                entry.get("secretName")
                for entry in (store.get("spec", {}).get("certificates") or [])
            ]
            if current == desired:
                return False
            try:
                self.kube.server_side_apply(
                    {
                        "apiVersion": "traefik.io/v1alpha1",
                        "kind": "TLSStore",
                        "metadata": {
                            "name": settings.tls_store_name,
                            "namespace": settings.tls_namespace,
                            "resourceVersion": store["metadata"]["resourceVersion"],
                        },
                        "spec": {"certificates": [{"secretName": n} for n in desired]},
                    },
                    field_manager=STORE_FIELD_MANAGER,
                )
            except AdapterCommandError as exc:
                if _is_stale_write(exc):
                    logger.info("Certificate store changed under us; recomputing")
                    continue
                raise
            logger.info("Certificate store now lists %s certificates", len(desired))
            return True
        raise ProvisionerError(
            f"Could not update the certificate store after {STORE_WRITE_ATTEMPTS} attempts"
        )

    def upsert_secret(
        self, *, namespace: str, name: str, string_data: dict[str, str], labels: dict[str, str]
    ) -> None:
        """Upsert a platform-owned Secret into a deployment's namespace."""
        self.kube.upsert_secret(
            namespace=namespace, name=name, string_data=string_data, labels=labels
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
