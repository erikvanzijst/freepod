"""Deployment identity: an owner-chosen name, description, icon, managed fields

`name` keeps the generated release name; the owner's name is `display_name`
(openspec deployment-identity-and-project-file D1). Every existing deployment
is named by the deployment-identity backfill rule, then made unique per owner
among live deployments with ` 2`, ` 3`...

Revision ID: f1d7c3a9e5b2
Revises: e3b9c5d1a7f4
Create Date: 2026-11-15

"""
from alembic import op
import sqlalchemy as sa


revision = "f1d7c3a9e5b2"
down_revision = "e3b9c5d1a7f4"
branch_labels = None
depends_on = None

NAME_MAX = 100


def _base_name(slug, product_name, hostname, handle) -> str:
    if slug == "custom" and hostname:
        label, _, rest = hostname.partition(".")
        suffix = f"-{handle}" if handle else None
        if rest and suffix and label.endswith(suffix) and len(label) > len(suffix):
            return label[: -len(suffix)]
        return hostname[:NAME_MAX]
    return product_name[:NAME_MAX]


def _free_name(base: str, taken: set[str]) -> str:
    candidate, n = base, 1
    while candidate.lower() in taken:
        n += 1
        suffix = f" {n}"
        candidate = base[: NAME_MAX - len(suffix)] + suffix
    return candidate


def upgrade() -> None:
    op.add_column("deployment", sa.Column("display_name", sa.String(), nullable=True))
    op.add_column("deployment", sa.Column("description", sa.Text(), nullable=True))
    op.add_column("deployment", sa.Column("rel_icon_path", sa.String(), nullable=True))
    op.add_column("deployment", sa.Column("icon_source_sha256", sa.String(), nullable=True))
    op.add_column(
        "deployment",
        sa.Column("managed_fields", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
    )

    bind = op.get_bind()
    rows = bind.execute(
        sa.text(
            """
            SELECT d.id, d.user_id, d.status, d.hostname, p.slug, p.name, u.handle
            FROM deployment d
            JOIN product_template_version t ON t.id = d.desired_template_id
            JOIN product p ON p.id = t.product_id
            JOIN "user" u ON u.id = d.user_id
            ORDER BY d.created_at, d.id
            """
        )
    ).all()
    taken: dict[int, set[str]] = {}
    for id_, user_id, status, hostname, slug, product_name, handle in rows:
        base = _base_name(slug, product_name, hostname, handle)
        if status == "deleted":
            name = base
        else:
            owner_taken = taken.setdefault(user_id, set())
            name = _free_name(base, owner_taken)
            owner_taken.add(name.lower())
        bind.execute(
            sa.text("UPDATE deployment SET display_name = :n WHERE id = :id"),
            {"n": name, "id": id_},
        )

    op.alter_column("deployment", "display_name", nullable=False)
    op.create_index(
        "uq_deployment_display_name",
        "deployment",
        ["user_id", sa.text("lower(display_name)")],
        unique=True,
        postgresql_where=sa.text("status <> 'deleted'"),
    )


def downgrade() -> None:
    op.drop_index("uq_deployment_display_name", table_name="deployment")
    op.drop_column("deployment", "managed_fields")
    op.drop_column("deployment", "icon_source_sha256")
    op.drop_column("deployment", "rel_icon_path")
    op.drop_column("deployment", "description")
    op.drop_column("deployment", "display_name")
