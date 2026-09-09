"""
Models package — re-exports all models so ``from app.models import X`` keeps
working everywhere.

The models are split across three modules:
  - core.py:    User, Product, ProductTemplateVersion, Deployment,
                DeploymentReconcileJob (and their Base/Create/Update/Read
                variants).
  - billing.py: Plan, PlanTemplateVersion, Subscription (and their
                Base/Create/Update/Read variants), plus the BillingInterval,
                SubscriptionStatus, and PaymentStatus enums.
  - build.py:   Build (and its Base/Create/Read variants). Standalone: a build
                references a user and an artifact, never a deployment.
  - ssh_key.py: SshKey (and its Create/Read variants). Owned by a user and
                scoped to no deployment.
"""

from app.models.core import (  # noqa: F401
    _utcnow,
    ReleaseStatus,
    DeploymentBase,
    DeploymentCreate,
    DeploymentCreateResponse,
    DeploymentDatabaseORM,
    DeploymentORM,
    DeploymentRead,
    DeploymentReconcileJobBase,
    DeploymentReconcileJobORM,
    DeploymentReleaseBase,
    DeploymentReleaseORM,
    DeploymentReleaseRead,
    DeploymentReleaseWithBuildRead,
    DeploymentUpdate,
    DeploymentVarORM,
    ProductBase,
    ProductCreate,
    ProductORM,
    ProductRead,
    ProductReadBase,
    ProductTemplateVersionBase,
    ProductTemplateVersionCreate,
    ProductTemplateVersionORM,
    ProductTemplateVersionRead,
    ProductUpdate,
    ProductVisibility,
    ReleaseVarORM,
    DeploymentDatabaseRead,
    SftpCredentialsRead,
    SshEdgeRead,
    SQLModel,
    SubdomainClaim,
    SubdomainRead,
    TosAcceptanceCreate,
    TosAcceptanceRead,
    UserBase,
    UserCreate,
    UserORM,
    UserRead,
    VarRead,
    VarWriter,
    VarWrite,
    VarsRead,
    VarsWrite,
)

from app.models.build import (  # noqa: F401
    BuildBase,
    BuildCreate,
    BuildORM,
    BuildRead,
)

from app.models.ssh_key import (  # noqa: F401
    SshKeyCreate,
    SshKeyORM,
    SshKeyRead,
)

from app.models.billing import (  # noqa: F401
    BillingInterval,
    MolliePaymentORM,
    MolliePaymentStatus,
    PaymentStatus,
    PlanBase,
    PlanCreate,
    PlanORM,
    PlanRead,
    PlanReadBase,
    PlanTemplateVersionBase,
    PlanTemplateVersionCreate,
    PlanTemplateVersionORM,
    PlanTemplateVersionRead,
    PlanUpdate,
    SubscriptionBase,
    SubscriptionORM,
    SubscriptionRead,
    SubscriptionStatus,
)

# Rebuild DeploymentRead so Pydantic resolves the SubscriptionRead
# forward reference (defined in billing.py, referenced in core.py) and the
# DeploymentReleaseRead one (defined below it in core.py).
DeploymentRead.model_rebuild()
# Same reason, other direction: DeploymentReleaseWithBuildRead names BuildRead,
# which lives in build.py and is only imported above.
DeploymentReleaseWithBuildRead.model_rebuild()
