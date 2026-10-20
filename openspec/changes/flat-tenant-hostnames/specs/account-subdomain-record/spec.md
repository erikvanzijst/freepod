# Spec Delta

## REMOVED Requirements

### Requirement: An account holds at most one subdomain
**Reason**: The account subdomain is replaced by the account handle, which ends a flat tenant hostname instead of naming a DNS zone beneath the platform domain.
**Migration**: See `account-handle`. `user.subdomain` is renamed to `user.handle`, and `/api/me/subdomain` to `/api/me/handle`.

### Requirement: A subdomain is claimed once and never changes
**Reason**: The account subdomain is replaced by the account handle, which ends a flat tenant hostname instead of naming a DNS zone beneath the platform domain.
**Migration**: See `account-handle`. `user.subdomain` is renamed to `user.handle`, and `/api/me/subdomain` to `/api/me/handle`.

### Requirement: The operator CLI claims, and only claims
**Reason**: The account subdomain is replaced by the account handle, which ends a flat tenant hostname instead of naming a DNS zone beneath the platform domain.
**Migration**: See `account-handle`. `user.subdomain` is renamed to `user.handle`, and `/api/me/subdomain` to `/api/me/handle`.

### Requirement: A deleted account does not release its subdomain
**Reason**: The account subdomain is replaced by the account handle, which ends a flat tenant hostname instead of naming a DNS zone beneath the platform domain.
**Migration**: See `account-handle`. `user.subdomain` is renamed to `user.handle`, and `/api/me/subdomain` to `/api/me/handle`.

### Requirement: A candidate must be a single DNS label
**Reason**: The account subdomain is replaced by the account handle, which ends a flat tenant hostname instead of naming a DNS zone beneath the platform domain.
**Migration**: See `account-handle`. `user.subdomain` is renamed to `user.handle`, and `/api/me/subdomain` to `/api/me/handle`.

### Requirement: Reserved names are refused, from the list that already exists
**Reason**: The account subdomain is replaced by the account handle, which ends a flat tenant hostname instead of naming a DNS zone beneath the platform domain.
**Migration**: See `account-handle`. `user.subdomain` is renamed to `user.handle`, and `/api/me/subdomain` to `/api/me/handle`.

### Requirement: The account's subdomain is readable
**Reason**: The account subdomain is replaced by the account handle, which ends a flat tenant hostname instead of naming a DNS zone beneath the platform domain.
**Migration**: See `account-handle`. `user.subdomain` is renamed to `user.handle`, and `/api/me/subdomain` to `/api/me/handle`.

### Requirement: Availability is answered by the existing hostname check
**Reason**: The account subdomain is replaced by the account handle, which ends a flat tenant hostname instead of naming a DNS zone beneath the platform domain.
**Migration**: See `account-handle`. `user.subdomain` is renamed to `user.handle`, and `/api/me/subdomain` to `/api/me/handle`.
