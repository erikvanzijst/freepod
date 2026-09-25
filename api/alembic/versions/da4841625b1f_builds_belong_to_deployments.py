"""builds belong to deployments

Replaces ``build.user_id`` with a required ``build.deployment_id``; a build's owner
is its deployment's owner. Existing builds are linked to the deployment that
released them: by the build a release recorded, else by a release carrying the
build's image (``freepod deploy --no-build`` and API releases name no build),
taking the earliest matching release. Builds no release ever used are deleted;
their registry images are left in place.

Refuses to run while a build is queued or running: such a build cannot be linked
yet, and deleting it would pull the row out from under the build worker.

Revision ID: da4841625b1f
Revises: c6d7e8f9a0b1
Create Date: 2026-09-25

"""
from alembic import op
import sqlalchemy as sa


revision = "da4841625b1f"
down_revision = "c6d7e8f9a0b1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    in_flight = bind.execute(
        sa.text("SELECT count(*) FROM build WHERE status IN ('queued', 'running')")
    ).scalar_one()
    if in_flight:
        raise RuntimeError(
            f"{in_flight} build(s) are queued or running and cannot be linked to a "
            "deployment yet; retry once they have finished"
        )

    op.add_column("build", sa.Column("deployment_id", sa.Uuid(), nullable=True))

    # The owner check is belt and braces: an image reference names its owner, and
    # a build recorded on a release was already validated against it.
    bind.execute(
        sa.text(
            """
            UPDATE build b SET deployment_id = linked.deployment_id
            FROM (
                SELECT DISTINCT ON (r.build_id) r.build_id, r.deployment_id
                FROM deployment_release r
                JOIN deployment d ON d.id = r.deployment_id
                JOIN build b2 ON b2.id = r.build_id AND b2.user_id = d.user_id
                ORDER BY r.build_id, r.created_at, r.id
            ) linked
            WHERE b.id = linked.build_id
            """
        )
    )
    bind.execute(
        sa.text(
            """
            UPDATE build b SET deployment_id = linked.deployment_id
            FROM (
                SELECT DISTINCT ON (b2.id) b2.id AS build_id, r.deployment_id
                FROM build b2
                JOIN deployment_release r ON r.values_json->>'image' = b2.image
                JOIN deployment d ON d.id = r.deployment_id AND d.user_id = b2.user_id
                WHERE b2.deployment_id IS NULL AND b2.image IS NOT NULL
                ORDER BY b2.id, r.created_at, r.id
            ) linked
            WHERE b.id = linked.build_id
            """
        )
    )
    # Unlinked means no release names it or carries its image, so no release's
    # build_id can point here and the delete cannot violate that foreign key.
    bind.execute(sa.text("DELETE FROM build WHERE deployment_id IS NULL"))

    op.alter_column("build", "deployment_id", nullable=False)
    op.create_foreign_key(
        "build_deployment_id_fkey", "build", "deployment", ["deployment_id"], ["id"]
    )
    op.create_index("ix_build_deployment_id", "build", ["deployment_id"])

    op.drop_index("ix_build_user_id", table_name="build")
    op.drop_constraint("build_user_id_fkey", "build", type_="foreignkey")
    op.drop_column("build", "user_id")


def downgrade() -> None:
    op.add_column("build", sa.Column("user_id", sa.Integer(), nullable=True))
    op.execute(
        "UPDATE build b SET user_id = d.user_id FROM deployment d WHERE d.id = b.deployment_id"
    )
    op.alter_column("build", "user_id", nullable=False)
    op.create_foreign_key("build_user_id_fkey", "build", "user", ["user_id"], ["id"])
    op.create_index("ix_build_user_id", "build", ["user_id"])

    op.drop_index("ix_build_deployment_id", table_name="build")
    op.drop_constraint("build_deployment_id_fkey", "build", type_="foreignkey")
    op.drop_column("build", "deployment_id")
