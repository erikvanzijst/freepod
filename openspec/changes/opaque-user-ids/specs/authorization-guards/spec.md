# Spec Delta

## MODIFIED Requirements

### Requirement: Self-or-admin authorization dependency
The system SHALL provide a `require_self` FastAPI dependency function in `api/app/deps.py` that accepts `user_id: str` (auto-resolved from path parameters) and chains off `get_current_user`. It SHALL raise `HTTPException(status_code=403, detail="Forbidden")` when the authenticated user's `id` does not exactly equal `user_id` AND the user is not an admin. It SHALL return the `UserORM` instance when access is allowed.

#### Scenario: User accesses own resource
- **WHEN** a non-admin user with id="k7m2qx9d4hfa" accesses an endpoint guarded by `require_self` with path parameter user_id="k7m2qx9d4hfa"
- **THEN** the dependency returns the `UserORM` instance and the endpoint executes normally

#### Scenario: User accesses another user's resource
- **WHEN** a non-admin user with id="k7m2qx9d4hfa" accesses an endpoint guarded by `require_self` with path parameter user_id="7"
- **THEN** the dependency raises HTTP 403 Forbidden with detail "Forbidden"

#### Scenario: Admin accesses another user's resource
- **WHEN** an admin user with id="1" accesses an endpoint guarded by `require_self` with path parameter user_id="k7m2qx9d4hfa"
- **THEN** the dependency returns the `UserORM` instance and the endpoint executes normally (admin bypass)

#### Scenario: Pre-existing numeric id matches as text
- **WHEN** a non-admin user with id="5" accesses an endpoint guarded by `require_self` with path parameter user_id="5"
- **THEN** the dependency returns the `UserORM` instance and the endpoint executes normally
