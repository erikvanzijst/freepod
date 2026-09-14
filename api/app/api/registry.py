"""The tenant registry's token endpoint.

Called by the node's container runtime, never by a signed-in user: the
credential is in the request, so no route here depends on the session
identity, and oauth2-proxy lets both through (tf/app/login). It mints pull
access only (authenticated-tenant-registry D10). Spec: registry-authorization.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Form, HTTPException, Query, status
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from sqlmodel import Session

from app.config import get_settings
from app.db import get_session
from app.services import registry_tokens
from app.services.registry_tokens import (
    IssuedToken,
    RegistryCredentialException,
    RegistryGrantException,
    RegistryKeyException,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["registry"])

_basic = HTTPBasic(auto_error=False)
_CHALLENGE = {"WWW-Authenticate": 'Basic realm="registry"'}


def _issue(
    session: Session, *, service: str, username: str, password: str, scopes: list[str]
) -> IssuedToken:
    try:
        return registry_tokens.issue_pull_token(
            session,
            get_settings(),
            service=service,
            username=username,
            password=password,
            scopes=scopes,
        )
    except RegistryCredentialException as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, str(exc), _CHALLENGE) from exc
    except RegistryKeyException as exc:
        logger.error("Registry token endpoint unusable: %s", exc)
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc


@router.get("/registry/token", summary="Issue a registry pull token for a Basic credential")
def get_token(
    service: str = Query(...),
    scope: list[str] = Query(default=[]),
    credentials: HTTPBasicCredentials | None = Depends(_basic),
    session: Session = Depends(get_session),
) -> dict:
    if credentials is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "a credential is required", _CHALLENGE)
    issued = _issue(
        session,
        service=service,
        username=credentials.username,
        password=credentials.password,
        scopes=scope,
    )
    return {
        "token": issued.token,
        "access_token": issued.token,
        "expires_in": issued.expires_in,
        "issued_at": issued.issued_at_rfc3339,
    }


@router.post("/registry/token", summary="Issue a registry pull token for a password grant")
def post_token(
    grant_type: str = Form(...),
    service: str = Form(...),
    username: str = Form(""),
    password: str = Form(""),
    scope: str = Form(""),
    session: Session = Depends(get_session),
) -> dict:
    if grant_type != "password":
        raise RegistryGrantException(f"unsupported grant_type {grant_type!r}")
    issued = _issue(
        session, service=service, username=username, password=password, scopes=[scope]
    )
    return {
        "access_token": issued.token,
        "expires_in": issued.expires_in,
        "issued_at": issued.issued_at_rfc3339,
        "scope": issued.scope,
    }
