class CaelusException(Exception):
    pass


class IntegrityException(CaelusException):
    pass


class DeploymentInProgressException(CaelusException):
    pass


class NotFoundException(CaelusException):
    # Alias for compatibility with older code
    pass


class ValidationException(CaelusException):
    pass


class CodedException(CaelusException):
    """An error a client branches on by `code` rather than by its prose."""

    def __init__(self, message: str, *, code: str):
        self.code = code
        super().__init__(message)


class ConflictException(CodedException):
    pass


class InvalidInputException(CodedException):
    pass


class RateLimitedException(CodedException):
    pass


class UpstreamException(CodedException):
    """Something the request depends on outside the platform did not answer as needed."""


class HostnameException(CaelusException):
    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(reason)


# Backward‑compatible alias expected by the CLI tests
NotFoundError = NotFoundException
