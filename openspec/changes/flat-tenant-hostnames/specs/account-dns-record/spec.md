# Spec Delta

## REMOVED Requirements

### Requirement: An account that deploys gets a wildcard record
**Reason**: Tenant hostnames are single labels under the tenant domain, which one static wildcard record covers. The platform no longer writes DNS records per account.
**Migration**: Existing per-account records are left in place, unmanaged, until a later change deletes them. The DNS provider adapter and its credentials are removed from the API.

### Requirement: The record must exist before the certificate is requested
**Reason**: Tenant hostnames are single labels under the tenant domain, which one static wildcard record covers. The platform no longer writes DNS records per account.
**Migration**: Existing per-account records are left in place, unmanaged, until a later change deletes them. The DNS provider adapter and its credentials are removed from the API.

### Requirement: Only the wildcard is created, not the account's own name
**Reason**: Tenant hostnames are single labels under the tenant domain, which one static wildcard record covers. The platform no longer writes DNS records per account.
**Migration**: Existing per-account records are left in place, unmanaged, until a later change deletes them. The DNS provider adapter and its credentials are removed from the API.

### Requirement: The DNS provider is reached through an adapter
**Reason**: Tenant hostnames are single labels under the tenant domain, which one static wildcard record covers. The platform no longer writes DNS records per account.
**Migration**: Existing per-account records are left in place, unmanaged, until a later change deletes them. The DNS provider adapter and its credentials are removed from the API.

### Requirement: A failed DNS write is visible and does not corrupt state
**Reason**: Tenant hostnames are single labels under the tenant domain, which one static wildcard record covers. The platform no longer writes DNS records per account.
**Migration**: Existing per-account records are left in place, unmanaged, until a later change deletes them. The DNS provider adapter and its credentials are removed from the API.
