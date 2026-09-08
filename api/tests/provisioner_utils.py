from __future__ import annotations

from app.provisioner import HelmReleaseOperationResult


class FakeProvisioner:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []
        self.raise_on_upgrade: Exception | None = None
        self.raise_on_certificate: Exception | None = None
        self.helm_revisions: dict[str, int] = {}

    def ensure_namespace(self, *, name: str):
        self.calls.append(("ensure_namespace", {"name": name}))
        return None

    def ensure_tenant_isolation(self, *, namespace: str):
        self.calls.append(("ensure_tenant_isolation", {"namespace": namespace}))
        return None

    def ensure_account_certificate(self, *, fqdn: str):
        self.calls.append(("ensure_account_certificate", {"fqdn": fqdn}))
        if self.raise_on_certificate is not None:
            raise self.raise_on_certificate
        return "acct-" + fqdn.replace(".", "-")

    def helm_upgrade_install(
        self,
        *,
        release_name: str,
        namespace: str,
        chart_ref: str,
        chart_version: str,
        chart_digest: str | None,
        values: dict,
        timeout: int,
        atomic: bool,
        wait: bool,
    ):
        self.calls.append(
            (
                "helm_upgrade_install",
                {
                    "release_name": release_name,
                    "namespace": namespace,
                    "chart_ref": chart_ref,
                    "chart_version": chart_version,
                    "chart_digest": chart_digest,
                    "values": values,
                    "timeout": timeout,
                    "atomic": atomic,
                    "wait": wait,
                },
            )
        )
        if self.raise_on_upgrade is not None:
            raise self.raise_on_upgrade
        # A real Helm apply reports the revision it produced, which the
        # reconciler records on the release. Counted per release name so a
        # second apply of the same deployment reads 2, as Helm's would.
        self.helm_revisions[release_name] = self.helm_revisions.get(release_name, 0) + 1
        return HelmReleaseOperationResult(
            release_name=release_name,
            namespace=namespace,
            changed=True,
            status="deployed",
            revision=self.helm_revisions[release_name],
        )

    def helm_uninstall(self, *, release_name: str, namespace: str, timeout: int, wait: bool):
        self.calls.append(
            (
                "helm_uninstall",
                {"release_name": release_name, "namespace": namespace, "timeout": timeout, "wait": wait},
            )
        )
        return None

    def delete_secrets_by_label(
        self, *, namespace: str, selector: str, except_name: str | None = None
    ):
        self.calls.append(
            (
                "delete_secrets_by_label",
                {"namespace": namespace, "selector": selector, "except_name": except_name},
            )
        )
        return None

    def delete_namespace(self, *, name: str):
        self.calls.append(("delete_namespace", {"name": name}))
        return None

    def upsert_secret(
        self, *, namespace: str, name: str, string_data: dict[str, str], labels: dict[str, str]
    ):
        self.calls.append(
            (
                "upsert_secret",
                {
                    "namespace": namespace,
                    "name": name,
                    "string_data": string_data,
                    "labels": labels,
                },
            )
        )
        return None
