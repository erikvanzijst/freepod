# Spec Delta

## REMOVED Requirements

### Requirement: The client never claims a subdomain
**Reason**: The client's missing-subdomain refusal becomes its missing-handle refusal.
**Migration**: See `cli-handle-required`. The refusal code is `handle_required`.

### Requirement: A deploy without a subdomain stops in preflight
**Reason**: The client's missing-subdomain refusal becomes its missing-handle refusal.
**Migration**: See `cli-handle-required`. The refusal code is `handle_required`.

### Requirement: The refusal names its cause and directs the user
**Reason**: The client's missing-subdomain refusal becomes its missing-handle refusal.
**Migration**: See `cli-handle-required`. The refusal code is `handle_required`.

### Requirement: Authentication is never gated on holding a subdomain
**Reason**: The client's missing-subdomain refusal becomes its missing-handle refusal.
**Migration**: See `cli-handle-required`. The refusal code is `handle_required`.
