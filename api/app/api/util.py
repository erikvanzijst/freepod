import logging

from starlette.requests import Request
from starlette.responses import JSONResponse

from app.services.errors import (
    CaelusException,
    ConflictException,
    DeploymentInProgressException,
    InvalidInputException,
    RateLimitedException,
    UpstreamException,
    HostnameException,
    IntegrityException,
    NotFoundException,
    ValidationException,
)

ERROR_STATUS = {
    HostnameException: 409,
    IntegrityException: 409,
    DeploymentInProgressException: 409,
    NotFoundException: 404,
    ValidationException: 400,
    ConflictException: 409,
    InvalidInputException: 422,
    RateLimitedException: 429,
    UpstreamException: 502,
}

logger = logging.getLogger(__name__)


def _status_for(exc: Exception) -> int:
    """Map an exception to a status code, honouring subclasses.

    Walks the MRO rather than looking up `type(exc)` exactly, so a service that
    raises a *more specific* error -- `ValidationException` subclassed to carry
    a distinct failure a caller may want to catch -- still answers 400 rather
    than falling through to 500. Most specific wins, since the MRO is ordered
    that way.
    """
    for klass in type(exc).__mro__:
        if klass in ERROR_STATUS:
            return ERROR_STATUS[klass]
    return 500


def _exception_handler(request: Request, exc: Exception):
    status = _status_for(exc)
    if status >= 500:
        logger.exception("Unhandled application error for path=%s: %s", request.url.path, exc)
    else:
        logger.warning("Request failed path=%s status=%s error=%s", request.url.path, status, exc)
    body = {"detail": str(exc)}
    # A stable identifier for conditions that share a status code and would
    # otherwise only be told apart by matching on prose. Omitted entirely
    # unless the raising service supplied one.
    code = getattr(exc, "code", None)
    if isinstance(code, str) and code:
        body["code"] = code
    return JSONResponse(body, status_code=status)


def register_exception_handlers(app):
    app.exception_handler(CaelusException)(_exception_handler)
    # app.exception_handler(ValidationError)(_exception_handler)
