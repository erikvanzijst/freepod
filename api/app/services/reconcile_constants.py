from __future__ import annotations

DEPLOYMENT_STATUS_PENDING = "pending"
DEPLOYMENT_STATUS_PROVISIONING = "provisioning"
DEPLOYMENT_STATUS_READY = "ready"
DEPLOYMENT_STATUS_DELETING = "deleting"
DEPLOYMENT_STATUS_ERROR = "error"
DEPLOYMENT_STATUS_DELETED = "deleted"

DEPLOYMENT_STATUSES: tuple[str, ...] = (
    DEPLOYMENT_STATUS_PENDING,
    DEPLOYMENT_STATUS_PROVISIONING,
    DEPLOYMENT_STATUS_READY,
    DEPLOYMENT_STATUS_DELETING,
    DEPLOYMENT_STATUS_DELETED,
    DEPLOYMENT_STATUS_ERROR,
)

JOB_STATUS_QUEUED = "queued"
JOB_STATUS_RUNNING = "running"
JOB_STATUS_DONE = "done"
JOB_STATUS_FAILED = "failed"

JOB_STATUSES: tuple[str, ...] = (
    JOB_STATUS_QUEUED,
    JOB_STATUS_RUNNING,
    JOB_STATUS_DONE,
    JOB_STATUS_FAILED,
)

JOB_REASON_CREATE = "create"
JOB_REASON_UPDATE = "update"
JOB_REASON_DELETE = "delete"
# Informational only: the reconciler decides from the pointers, never the reason.
JOB_REASON_POWER = "power"

JOB_REASONS: tuple[str, ...] = (
    JOB_REASON_CREATE,
    JOB_REASON_UPDATE,
    JOB_REASON_DELETE,
    JOB_REASON_POWER,
)

POWER_STATE_RUNNING = "running"
POWER_STATE_STOPPED = "stopped"

POWER_STATES: tuple[str, ...] = (POWER_STATE_RUNNING, POWER_STATE_STOPPED)

POWER_REASON_MANUAL = "manual"
# Reserved for stopping a deployment in payment arrears; nothing produces it yet.
POWER_REASON_PAYMENT = "payment"
# Set and lifted only by an operator, while the platform works on the deployment.
POWER_REASON_MAINTENANCE = "maintenance"

POWER_REASONS: tuple[str, ...] = (
    POWER_REASON_MANUAL,
    POWER_REASON_PAYMENT,
    POWER_REASON_MAINTENANCE,
)
