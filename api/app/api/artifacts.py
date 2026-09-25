from __future__ import annotations

from fastapi import APIRouter, Depends, status

from app.deps import get_current_user
from app.models import UserORM
from app.services import artifacts as artifact_service
from app.services.artifacts import ArtifactUploadSlot

router = APIRouter(tags=["artifacts"])


@router.post(
    "/artifacts",
    response_model=ArtifactUploadSlot,
    status_code=status.HTTP_201_CREATED,
    summary="Mint an upload slot for a project archive",
    response_description=(
        "An ArtifactUploadSlot: the generated `artifact_id`, the `url` to POST "
        "the archive to, the presigned policy `fields` to send verbatim, and "
        "the `max_bytes` and `expires_in` the slot was issued under."
    ),
    responses={
        201: {
            "description": (
                "A slot was issued. Nothing is persisted — an upload that is "
                "never started or never finishes leaves no state behind, and "
                "the artifact itself is later expired by the bucket's "
                "lifecycle policy."
            )
        },
        404: {"description": "The request carried no authenticated identity."},
    },
)
def create_artifact_upload_slot(
    current_user: UserORM = Depends(get_current_user),
) -> ArtifactUploadSlot:
    """Issue credentials to upload one project archive directly to the object store.

    Phase one of three: mint a slot, PUT the bytes at the object store with the
    returned form fields, then
    `POST /api/users/{user_id}/deployments/{deployment_id}/builds` with the
    `artifact_id`.

    The endpoint takes **no request body**. The object key is derived entirely
    from the authenticated caller and a server-generated identifier, so there
    is no key, path, or URL a client could supply that would change where the
    slot points — and therefore no ownership check to bypass.
    """
    return artifact_service.mint_upload_slot(current_user.id)
