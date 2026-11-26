from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, File, Form, Path, Query, Response, UploadFile, status
from sqlmodel import Session

from app.db import get_session
from app.deps import get_current_user, require_admin
from app.models import (
    FeedbackCreated,
    FeedbackListRead,
    FeedbackRead,
    FeedbackTopic,
    FeedbackUpdate,
    UserORM,
)
from app.services import feedback as feedback_service
from app.services.images import FEEDBACK_SCREENSHOT_MAX_BYTES

router = APIRouter(prefix="/feedback", tags=["feedback"])

ID_DESCRIPTION = "ID of the feedback submission."


@router.post(
    "",
    response_model=FeedbackCreated,
    status_code=status.HTTP_201_CREATED,
    summary="Send feedback",
    response_description="The stored submission's id.",
    responses={
        201: {"description": "The feedback was stored."},
        404: {"description": "The request carried no authenticated identity."},
        422: {
            "description": "The submission was refused. The body's `code` names which check "
            "failed: `invalid_topic`, `message_required`, `message_too_long`, `invalid_page` "
            "or `invalid_screenshot`."
        },
        429: {"description": "Too many submissions in 24 hours (`code`: `feedback_limit`)."},
    },
)
def submit_feedback(
    topic: str = Form(..., description="`bug`, `idea` or `other`."),
    message: str = Form(..., description="The feedback, up to 5000 characters."),
    page: str = Form(..., description="The page's path and query, such as `/apps?category=photos`."),
    user_agent: str | None = Form(None, description="The browser's user agent."),
    viewport: str | None = Form(None, description="The viewport size, such as `1440x900`."),
    ui_build: str | None = Form(None, description="The commit the sender's UI was built from."),
    diagnostics: str | None = Form(None, description="A JSON array of the page's recent problems."),
    screenshot: UploadFile | None = File(None, description="A PNG, JPEG or WebP image, at most 2 MB."),
    current_user: UserORM = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> FeedbackCreated:
    """Send feedback about a page of Freepod.

    ## Authorization
    Any signed-in user. The sender is always the caller: any sender, email,
    status or API build in the request is ignored.

    ## Behavior
    The page's fragment and secret-looking query parameters (`code`, `state`,
    `token`, `*_token`, `*secret`) are dropped. A screenshot is re-encoded, so
    none of the uploaded file's metadata is kept. Each user may send 20
    submissions in any 24 hours.

    ## Errors
    - **422** — a field failed validation; `code` names which.
    - **429** — the daily limit is reached; the message says when it resets.
    """
    data = screenshot.file.read(FEEDBACK_SCREENSHOT_MAX_BYTES + 1) if screenshot is not None else None
    row = feedback_service.submit_feedback(
        session,
        user=current_user,
        topic=topic,
        message=message,
        page=page,
        user_agent=user_agent,
        viewport=viewport,
        ui_build=ui_build,
        diagnostics=diagnostics,
        screenshot=data,
    )
    return FeedbackCreated(id=row.id)


@router.get(
    "",
    response_model=FeedbackListRead,
    summary="List feedback",
    response_description="One page of submissions, newest first, and the unread count.",
    responses={403: {"description": "Administrators only."}},
)
def list_feedback(
    state: Literal["open", "resolved", "all"] = Query("open", description="Which submissions to list."),
    topic: FeedbackTopic | None = Query(None, description="Only submissions with this topic."),
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=0, le=200, description="`0` returns only the counts."),
    _: UserORM = Depends(require_admin),
    session: Session = Depends(get_session),
) -> FeedbackListRead:
    """List submissions without their screenshots. `unread` counts every
    unread submission, whatever the filters."""
    return feedback_service.list_feedback(
        session, resolved={"open": False, "resolved": True}.get(state), topic=topic, offset=offset, limit=limit
    )


@router.get(
    "/{feedback_id}",
    response_model=FeedbackRead,
    summary="Read one feedback submission",
    responses={403: {"description": "Administrators only."}, 404: {"description": "No such feedback."}},
)
def get_feedback(
    feedback_id: int = Path(..., description=ID_DESCRIPTION),
    _: UserORM = Depends(require_admin),
    session: Session = Depends(get_session),
) -> FeedbackRead:
    """The whole submission. The first read by any administrator marks it read."""
    return feedback_service.get_feedback(session, feedback_id)


@router.get(
    "/{feedback_id}/screenshot",
    summary="Download a submission's screenshot",
    response_class=Response,
    responses={
        200: {"content": {"image/webp": {}}, "description": "The screenshot."},
        403: {"description": "Administrators only."},
        404: {"description": "No such feedback, or it has no screenshot."},
    },
)
def get_feedback_screenshot(
    feedback_id: int = Path(..., description=ID_DESCRIPTION),
    _: UserORM = Depends(require_admin),
    session: Session = Depends(get_session),
) -> Response:
    shot = feedback_service.get_screenshot(session, feedback_id)
    return Response(
        content=bytes(shot.data),
        media_type=shot.media_type,
        headers={"Cache-Control": "private, no-store"},
    )


@router.patch(
    "/{feedback_id}",
    response_model=FeedbackRead,
    summary="Resolve or reopen a submission",
    responses={403: {"description": "Administrators only."}, 404: {"description": "No such feedback."}},
)
def update_feedback(
    payload: FeedbackUpdate,
    feedback_id: int = Path(..., description=ID_DESCRIPTION),
    admin: UserORM = Depends(require_admin),
    session: Session = Depends(get_session),
) -> FeedbackRead:
    """`resolved: true` records the time and the administrator; `false`
    reopens it. Setting the state it is already in changes nothing."""
    return feedback_service.set_resolved(session, feedback_id, resolved=payload.resolved, admin=admin)
