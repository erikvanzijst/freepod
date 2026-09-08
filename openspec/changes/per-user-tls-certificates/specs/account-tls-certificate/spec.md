## Purpose

The TLS certificate an account holds: one wildcard covering every hostname its applications
will ever be addressed at, issued once and renewed forever, held in a platform namespace
rather than in any tenant's.

## ADDED Requirements

### Requirement: An account holds one wildcard certificate

The platform MUST hold at most one certificate per account, covering
`*.<subdomain>.<platform domain>` and `<subdomain>.<platform domain>`, requested through the
platform's DNS-01 issuer.

One per account rather than one per deployment is a rate-limit decision, and the reasoning is
worth keeping: certificate authorities limit new certificates per registered domain per week,
and they refuse repeated issuance for an identical set of names. A per-deployment scheme makes
the platform's weekly ceiling a function of deployments — which churn, so one account
iterating on an application can exhaust the allowance for everyone — and locks that account out
of TLS entirely once it has recreated the same hostname a handful of times in a week. A
per-account certificate tracks signups, which cannot be churned because a subdomain is
permanent and never released.

The account's own name is included alongside the wildcard even though nothing resolves there
today. Both names validate against the same challenge record, so it costs no additional DNS
and no additional certificate — and adding it later would be a different set of names, and
therefore a new certificate against the weekly allowance.

#### Scenario: The certificate covers every application hostname

- **WHEN** an account's certificate is inspected
- **THEN** its names include `*.<subdomain>.<platform domain>` and
  `<subdomain>.<platform domain>`

#### Scenario: A second deployment reuses the certificate

- **WHEN** an account that already holds a certificate creates another deployment
- **THEN** no further certificate is requested for it

#### Scenario: Recreating an application does not reissue

- **WHEN** an account deletes a deployment and creates another at the same hostname
- **THEN** the account's existing certificate continues to cover it, and nothing is reissued

### Requirement: Account certificates use an elliptic-curve key

Account certificates MUST be issued with an ECDSA P-256 key rather than the issuer client's
RSA default.

Both of this design's costs that grow with the number of accounts are reduced by it. The
ingress controller re-reads and re-parses every certificate in its store on every configuration
rebuild, and parsing an RSA private key includes a consistency validation that an elliptic-curve
key does not; and the stored secret is smaller, which is what the reconciler transfers when it
derives the store's membership. Measured on the first issued account certificate: 7.8 KB of
JSON against 10.8 KB for the platform's RSA wildcard, so about a quarter smaller rather than
the two thirds an earlier draft of this claimed — the certificate chain dominates the secret,
and only the key part shrinks by the order of magnitude the algorithm suggests.

#### Scenario: Issued keys are elliptic-curve

- **WHEN** an account's certificate is issued
- **THEN** its private key is ECDSA P-256

#### Scenario: The platform default is not relied upon

- **WHEN** the certificate is declared
- **THEN** it states the key algorithm explicitly rather than inheriting the issuer client's
  default, which is RSA

### Requirement: The certificate is requested on the account's first deployment

The platform MUST request an account's certificate when it first deploys, and MUST NOT request
one when the account claims its subdomain.

A certificate is a rationed resource; a subdomain is not. Issuing at claim time would spend the
weekly allowance on accounts that never deploy anything, and the allowance is what limits how
many accounts the platform can onboard in a week.

#### Scenario: Claiming a subdomain issues nothing

- **WHEN** an account claims its subdomain and does not deploy
- **THEN** no certificate exists for it

#### Scenario: The first deployment triggers issuance

- **WHEN** that account later creates its first deployment
- **THEN** its certificate is requested

### Requirement: Certificates live in one platform namespace

Every account certificate MUST be held in a single platform-owned namespace, together with the
platform's own wildcard, and MUST NOT be created in any tenant namespace.

A tenant namespace is deleted with its deployment and is readable by the code running in it. A
certificate that outlives every individual deployment and belongs to none of them does not
live there.

#### Scenario: No certificate material reaches a tenant namespace

- **WHEN** a tenant namespace is inspected after its deployment is reconciled
- **THEN** it contains no account certificate and no copy of one

#### Scenario: Deleting a deployment does not disturb the certificate

- **WHEN** a deployment is deleted and its namespace removed
- **THEN** the account's certificate is unaffected

### Requirement: Nothing deletes an account certificate

The platform MUST NOT delete an account's certificate — not when its deployments are removed,
and not when the account is closed.

A subdomain is never released, so the certificate can never become someone else's to hold, and
reissuing one that was deleted spends the weekly allowance to return to where the platform
already was.

#### Scenario: An account with no deployments keeps its certificate

- **WHEN** an account's last deployment is deleted
- **THEN** its certificate remains and continues to renew

### Requirement: Renewal is the issuer's alone

Nothing in the platform MUST act on renewal. The certificate's secret keeps its name across
renewals, so every reference to it stays correct without being rewritten, and no component
copies, mirrors, refreshes or re-registers it.

A design in which renewal requires action is a design with a sixty-day fuse: the failure
appears long after the change that caused it, as an expired certificate rather than as an
error.

#### Scenario: Renewal is invisible

- **WHEN** an account's certificate is renewed
- **THEN** its secret is updated in place, its name is unchanged, and nothing else in the
  platform acts

### Requirement: The reconcile waits for the certificate before completing

When an account's certificate has been requested and is not yet issued, the reconcile MUST NOT
complete the deployment. It MUST leave the deployment in its provisioning state, defer its own
job to run again shortly, and re-check on the next run — completing only once the certificate
is issued and the store has been brought up to date.

Waiting is what makes the certificate reach the store at all. Membership is derived from the
certificates that exist, so a reconcile that finishes before issuance writes a list that does
not contain the new certificate and has no reason to write again. Nothing else would notice:
the next opportunity is the next reconcile of any deployment on the platform, which on a quiet
platform may be days away or may never come. An account would hold a valid certificate the
ingress controller had never been told about.

Deferring MUST NOT hold a worker or its job lease while it waits.

#### Scenario: Issuance slower than installation is waited for

- **WHEN** an account's first deployment finishes installing and its certificate is not yet
  issued
- **THEN** the deployment remains provisioning, the job is deferred, and no worker is held

#### Scenario: The retry completes the work

- **WHEN** a deferred reconcile runs and finds the certificate issued
- **THEN** the store is brought up to date and the deployment completes

#### Scenario: Waiting does not consume the lease

- **WHEN** a reconcile defers for a certificate
- **THEN** its job returns to the queue with a later eligibility time and no lease held, rather
  than sleeping inside the reconcile

### Requirement: Waiting is bounded, and exhausting it fails the deployment

The reconcile MUST stop waiting after a bounded period measured from when the work was first
queued, and MUST then fail the deployment the way any other provisioning failure fails it —
recording the cause on the deployment and leaving it in an error state.

An account certificate is treated as a precondition for its deployments from the moment this
capability exists, not from the moment hostnames move under account subdomains. The alternative
is a leniency that has to be found and reversed later, in a system where the reason for it has
been forgotten and where the failure it hides — an application published under a name it cannot
serve a valid certificate for — is worse than the deployment that never completed.

The consequence is accepted: an exhausted certificate allowance, an issuer outage or a DNS
provider outage will fail the first deployment of accounts that do not yet hold a certificate.
That is the behaviour those failures should have, and having it now means it is exercised and
understood before anything depends on it.

#### Scenario: A certificate that never arrives fails its deployment

- **WHEN** an account's certificate has not been issued within the waiting budget
- **THEN** the deployment is left in an error state with the cause recorded on it

#### Scenario: The failure names its own cause

- **WHEN** a deployment fails for want of a certificate
- **THEN** the recorded cause identifies the certificate, and is not reported as a chart,
  release or installation failure

#### Scenario: The certificate survives the failure and a retry proceeds

- **WHEN** a deployment has failed waiting, and the certificate is issued afterwards
- **THEN** the certificate is not deleted, and a subsequent reconcile of that deployment finds it
  issued and completes

### Requirement: A certificate that cannot be provisioned fails its deployment

A deployment MUST NOT complete while its account's certificate is absent. A failure to create
the account's DNS record, to request the certificate, or to see it issued within the waiting
budget MUST fail the reconcile, and MUST be reported to operators as well as recorded on the
deployment.

#### Scenario: A DNS failure stops the deployment

- **WHEN** the account's DNS record cannot be created
- **THEN** no certificate is requested, and the deployment does not complete

#### Scenario: A refused issuance stops the deployment

- **WHEN** issuance is refused — an exhausted allowance, a rejected challenge, an issuer outage
- **THEN** the deployment does not complete, and the refusal reaches operators

#### Scenario: Retrying is possible without operator intervention

- **WHEN** the cause of a failure clears
- **THEN** a further reconcile of the deployment succeeds without anything being reset by hand
