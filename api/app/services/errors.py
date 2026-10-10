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


class HostnameException(CaelusException):
    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(reason)


class UserResolutionConflictException(IntegrityException):
    """Caller resolution would violate the active-user uniqueness guarantee.

    Raised when binding a subject to a record would leave two active records
    claiming the same email (design.md D7): a stale record still holds an
    address another identity now owns. The request fails loudly rather than
    mutate or delete another account's row; the state needs manual repair. A
    409 with a stable `code` so a client can branch on it rather than prose.
    """

    def __init__(self, message: str):
        self.code = "user_resolution_conflict"
        super().__init__(message)


# Backward‑compatible alias expected by the CLI tests
NotFoundError = NotFoundException
