"""The Kubernetes side of a build: the Job manifest, and the calls against it.

Everything that talks to the cluster goes through ``BuildJobClient``, so the
worker's logic can be tested against a fake without a cluster. The real
implementation shells out to ``kubectl``, matching ``app/provisioner.py``.

One call deliberately does *not* use ``app/proc.py``: reading a build's output.
``proc.CommandRunner`` is typed ``CompletedProcess[str]`` and decodes, and build
output is a tenant-controlled byte stream that must reach the ``bytea`` log
column unmodified — see design D12.
"""

from __future__ import annotations

import json
import logging
import subprocess
from tempfile import NamedTemporaryFile
from typing import Any, Protocol
from uuid import UUID

from app.config import CaelusSettings
from app.proc import run_command

logger = logging.getLogger(__name__)

# Selects a build's pods without depending on the Job's own naming.
BUILD_ID_LABEL = "caelus.dev/build-id"

JOB_NAME_PREFIX = "build-"

# The build tree. Bounded because a tenant controls what gets written here:
# the extracted source (capped in the builder at 800 MiB) plus whatever the
# build itself produces.
WORK_DIR = "/home/user/work"
WORK_SIZE_LIMIT = "2Gi"

# BuildKit's own state and layer cache. Much larger than the work tree because
# a dependency install writes every layer here. BuildKit's default GC policy is
# sized for a dedicated builder (it reserves 6 GB and tolerates 46 GB), which
# would swallow this node's whole disk, so the bound is the emptyDir's rather
# than BuildKit's.
BUILDKIT_DIR = "/home/user/.local/share/buildkit"
BUILDKIT_SIZE_LIMIT = "6Gi"

# Resource envelope for one build on a shared 4-thread node. The CPU limit
# leaves two threads for tenant traffic, which is the point: a dependency
# install will otherwise saturate everything for minutes. ephemeral-storage
# must cover both emptyDirs, since they count against it.
CPU_REQUEST = "500m"
CPU_LIMIT = "2"
MEMORY_REQUEST = "1Gi"
MEMORY_LIMIT = "4Gi"
EPHEMERAL_STORAGE_LIMIT = "8Gi"

# How long a finished Job (and its pod, and therefore its logs) survives.
# This is the window in which a restarted worker can still adopt an outcome
# rather than losing it, so it is generous relative to the poll interval.
TTL_SECONDS_AFTER_FINISHED = 3600


def job_name(build_id: UUID | str) -> str:
    return f"{JOB_NAME_PREFIX}{build_id}"


def build_job_manifest(
    *,
    build_id: UUID | str,
    user_id: int,
    artifact_url: str,
    settings: CaelusSettings,
) -> dict[str, Any]:
    """The Job that runs one build.

    Security posture, and why each part is what it is:

    - ``serviceAccountName`` is the permissionless builder account and
      ``automountServiceAccountToken`` is false, so there is no Kubernetes
      credential in the pod even by accident.
    - ``seccompProfile`` and ``appArmorProfile`` are ``Unconfined`` because
      rootless BuildKit must create a user namespace and mount inside it, which
      the container's default profiles block. This is why the namespace runs
      under Pod Security ``privileged``; the pod is still unprivileged, running
      as uid 1000 with no host mounts and no host network.
    - ``backoffLimit: 0`` — a failed build is terminal and is never retried
      automatically. Recovery is creating a new build.
    - ``activeDeadlineSeconds`` puts the deadline where Kubernetes will enforce
      it even if no worker is alive; the worker only intervenes past a grace
      period, as a backstop.
    """
    if not settings.builder_image:
        raise ValueError(
            "CAELUS_BUILDER_IMAGE is not set; the build worker cannot run a build "
            "without one. It is supplied by Terraform (builder_image in tf/app)."
        )

    name = job_name(build_id)
    return {
        "apiVersion": "batch/v1",
        "kind": "Job",
        "metadata": {
            "name": name,
            "namespace": settings.builds_namespace,
            "labels": {
                BUILD_ID_LABEL: str(build_id),
                "app.kubernetes.io/managed-by": "caelus",
                "app.kubernetes.io/component": "build",
            },
        },
        "spec": {
            "backoffLimit": 0,
            "activeDeadlineSeconds": settings.build_deadline_seconds,
            "ttlSecondsAfterFinished": TTL_SECONDS_AFTER_FINISHED,
            "template": {
                "metadata": {
                    "labels": {
                        BUILD_ID_LABEL: str(build_id),
                        "app.kubernetes.io/managed-by": "caelus",
                        "app.kubernetes.io/component": "build",
                    },
                },
                "spec": {
                    "restartPolicy": "Never",
                    "serviceAccountName": "caelus-builder",
                    "automountServiceAccountToken": False,
                    "securityContext": {
                        "runAsUser": 1000,
                        "runAsGroup": 1000,
                        "seccompProfile": {"type": "Unconfined"},
                        "appArmorProfile": {"type": "Unconfined"},
                    },
                    "containers": [
                        {
                            "name": "build",
                            "image": settings.builder_image,
                            # The pod's result. Kubernetes surfaces this through
                            # pod status, which is how the build reports its
                            # image without holding any credential.
                            "terminationMessagePath": "/dev/termination-log",
                            "terminationMessagePolicy": "File",
                            "env": [
                                {"name": "CAELUS_ARTIFACT_URL", "value": artifact_url},
                                {"name": "CAELUS_USER_ID", "value": str(user_id)},
                                {"name": "CAELUS_BUILD_ID", "value": str(build_id)},
                                {"name": "CAELUS_REGISTRY", "value": settings.build_registry_host},
                                # Scopes the builder's per-owner layer cache
                                # repository. The builds namespace is the one
                                # value that already differs between dev and
                                # prod, which is what stops their independent
                                # user id sequences colliding on one cache in
                                # the registry both environments share.
                                {
                                    "name": "CAELUS_CACHE_SCOPE",
                                    "value": settings.builds_namespace,
                                },
                                {"name": "CAELUS_WORKDIR", "value": WORK_DIR},
                                {
                                    "name": "CAELUS_ARTIFACT_MAX_BYTES",
                                    "value": str(settings.artifact_max_bytes),
                                },
                            ],
                            "resources": {
                                "requests": {
                                    "cpu": CPU_REQUEST,
                                    "memory": MEMORY_REQUEST,
                                },
                                "limits": {
                                    "cpu": CPU_LIMIT,
                                    "memory": MEMORY_LIMIT,
                                    "ephemeral-storage": EPHEMERAL_STORAGE_LIMIT,
                                },
                            },
                            "volumeMounts": [
                                {"name": "work", "mountPath": WORK_DIR},
                                {"name": "buildkit", "mountPath": BUILDKIT_DIR},
                            ],
                        }
                    ],
                    "volumes": [
                        {"name": "work", "emptyDir": {"sizeLimit": WORK_SIZE_LIMIT}},
                        {"name": "buildkit", "emptyDir": {"sizeLimit": BUILDKIT_SIZE_LIMIT}},
                    ],
                },
            },
        },
    }


class BuildJobClient(Protocol):
    """The cluster operations a build worker performs.

    Narrow on purpose: this is the seam the worker's tests replace, so every
    method here is one the fake has to be honest about.
    """

    def create_job(self, manifest: dict[str, Any]) -> None: ...

    def get_job(self, name: str) -> dict[str, Any] | None: ...

    def delete_job(self, name: str) -> None: ...

    def read_log(self, build_id: str) -> bytes | None: ...

    def read_termination_message(self, build_id: str) -> str | None: ...


class KubectlBuildJobClient:
    """``BuildJobClient`` over the ``kubectl`` binary."""

    def __init__(self, *, namespace: str) -> None:
        self._namespace = namespace

    def create_job(self, manifest: dict[str, Any]) -> None:
        with NamedTemporaryFile(mode="w", encoding="utf-8", suffix=".json") as handle:
            json.dump(manifest, handle)
            handle.flush()
            run_command(
                ["kubectl", "create", "-n", self._namespace, "-f", handle.name],
                error_message="Failed to create build Job",
            )

    def get_job(self, name: str) -> dict[str, Any] | None:
        """The Job, or None when it does not exist.

        A missing Job is an ordinary outcome — it may have been reaped by its
        TTL, or deleted by the deadline backstop — so it is not an error.
        """
        completed = subprocess.run(
            ["kubectl", "get", "job", name, "-n", self._namespace, "-o", "json"],
            capture_output=True,
            text=True,
            check=False,
        )
        if completed.returncode != 0:
            return None
        try:
            return json.loads(completed.stdout)
        except json.JSONDecodeError:
            logger.warning("Unparseable Job JSON for %s", name)
            return None

    def delete_job(self, name: str) -> None:
        subprocess.run(
            [
                "kubectl", "delete", "job", name,
                "-n", self._namespace,
                "--ignore-not-found=true",
                # The pod goes with the Job; leaving it would keep consuming
                # the node after the build has been given up on.
                "--cascade=foreground",
                "--wait=false",
            ],
            capture_output=True,
            check=False,
        )

    def read_log(self, build_id: str) -> bytes | None:
        """A build's output so far, as raw bytes.

        Deliberately not routed through ``app/proc.py``: that decodes to ``str``,
        and this output is tenant-controlled bytes bound for a ``bytea`` column.
        Decoding here would force a lossy conversion that also shifts the byte
        offsets clients poll the log endpoint with.

        Returns None when there is nothing to read yet (the pod has not started,
        or has already been reaped), which is not a failure.
        """
        completed = subprocess.run(
            [
                "kubectl", "logs",
                "-n", self._namespace,
                "-l", f"{BUILD_ID_LABEL}={build_id}",
                "--tail=-1",
                # Without this kubectl prints only the first pod's logs silently;
                # with backoffLimit 0 there is only ever one, but be explicit.
                "--max-log-requests=1",
            ],
            capture_output=True,
            check=False,
        )
        if completed.returncode != 0:
            return None
        return completed.stdout

    def read_termination_message(self, build_id: str) -> str | None:
        """The build container's termination message, if it has terminated."""
        completed = subprocess.run(
            [
                "kubectl", "get", "pods",
                "-n", self._namespace,
                "-l", f"{BUILD_ID_LABEL}={build_id}",
                "-o", "json",
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        if completed.returncode != 0:
            return None
        try:
            payload = json.loads(completed.stdout)
        except json.JSONDecodeError:
            return None
        for pod in payload.get("items", []):
            for status in pod.get("status", {}).get("containerStatuses", []):
                terminated = status.get("state", {}).get("terminated")
                if terminated and terminated.get("message"):
                    return terminated["message"]
        return None


def job_is_complete(job: dict[str, Any]) -> bool:
    return int(job.get("status", {}).get("succeeded") or 0) > 0


def job_is_failed(job: dict[str, Any]) -> bool:
    return int(job.get("status", {}).get("failed") or 0) > 0


def parse_image_from_termination_message(message: str | None) -> str | None:
    """The image reference a successful build reported, or None.

    The contract is a JSON object carrying an ``image`` key. A failure reports
    ``{"error": ...}`` with no ``image``, so requiring the key here is what
    makes a failure impossible to mistake for a success — and tenant build
    output cannot forge it, because this comes from the pod's termination
    message rather than from the log.
    """
    if not message:
        return None
    try:
        payload = json.loads(message)
    except (json.JSONDecodeError, TypeError):
        return None
    if not isinstance(payload, dict):
        return None
    image = payload.get("image")
    return image if isinstance(image, str) and image else None
