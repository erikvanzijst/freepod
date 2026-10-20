# Spec Delta

## REMOVED Requirements

### Requirement: An account holds one wildcard certificate
**Reason**: Tenant hostnames are served by the platform's default certificate, which covers the tenant domain's wildcard. The platform no longer requests, waits for, or lists a certificate per account.
**Migration**: Existing account certificates are left in place, renewed by cert-manager, so retired hostnames' redirects keep valid TLS until a later change deletes them. See `freepod-tls-termination` and `tenant-domain-edge`.

### Requirement: Account certificates use an elliptic-curve key
**Reason**: Tenant hostnames are served by the platform's default certificate, which covers the tenant domain's wildcard. The platform no longer requests, waits for, or lists a certificate per account.
**Migration**: Existing account certificates are left in place, renewed by cert-manager, so retired hostnames' redirects keep valid TLS until a later change deletes them. See `freepod-tls-termination` and `tenant-domain-edge`.

### Requirement: The certificate is requested on the account's first deployment
**Reason**: Tenant hostnames are served by the platform's default certificate, which covers the tenant domain's wildcard. The platform no longer requests, waits for, or lists a certificate per account.
**Migration**: Existing account certificates are left in place, renewed by cert-manager, so retired hostnames' redirects keep valid TLS until a later change deletes them. See `freepod-tls-termination` and `tenant-domain-edge`.

### Requirement: Certificates live in one platform namespace
**Reason**: Tenant hostnames are served by the platform's default certificate, which covers the tenant domain's wildcard. The platform no longer requests, waits for, or lists a certificate per account.
**Migration**: Existing account certificates are left in place, renewed by cert-manager, so retired hostnames' redirects keep valid TLS until a later change deletes them. See `freepod-tls-termination` and `tenant-domain-edge`.

### Requirement: Nothing deletes an account certificate
**Reason**: Tenant hostnames are served by the platform's default certificate, which covers the tenant domain's wildcard. The platform no longer requests, waits for, or lists a certificate per account.
**Migration**: Existing account certificates are left in place, renewed by cert-manager, so retired hostnames' redirects keep valid TLS until a later change deletes them. See `freepod-tls-termination` and `tenant-domain-edge`.

### Requirement: Renewal is the issuer's alone
**Reason**: Tenant hostnames are served by the platform's default certificate, which covers the tenant domain's wildcard. The platform no longer requests, waits for, or lists a certificate per account.
**Migration**: Existing account certificates are left in place, renewed by cert-manager, so retired hostnames' redirects keep valid TLS until a later change deletes them. See `freepod-tls-termination` and `tenant-domain-edge`.

### Requirement: The reconcile waits for the certificate before completing
**Reason**: Tenant hostnames are served by the platform's default certificate, which covers the tenant domain's wildcard. The platform no longer requests, waits for, or lists a certificate per account.
**Migration**: Existing account certificates are left in place, renewed by cert-manager, so retired hostnames' redirects keep valid TLS until a later change deletes them. See `freepod-tls-termination` and `tenant-domain-edge`.

### Requirement: Waiting is bounded, and exhausting it fails the deployment
**Reason**: Tenant hostnames are served by the platform's default certificate, which covers the tenant domain's wildcard. The platform no longer requests, waits for, or lists a certificate per account.
**Migration**: Existing account certificates are left in place, renewed by cert-manager, so retired hostnames' redirects keep valid TLS until a later change deletes them. See `freepod-tls-termination` and `tenant-domain-edge`.

### Requirement: A certificate that cannot be provisioned fails its deployment
**Reason**: Tenant hostnames are served by the platform's default certificate, which covers the tenant domain's wildcard. The platform no longer requests, waits for, or lists a certificate per account.
**Migration**: Existing account certificates are left in place, renewed by cert-manager, so retired hostnames' redirects keep valid TLS until a later change deletes them. See `freepod-tls-termination` and `tenant-domain-edge`.
