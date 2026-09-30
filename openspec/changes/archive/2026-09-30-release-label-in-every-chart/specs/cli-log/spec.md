## ADDED Requirements

### Requirement: Following is explicit, and pinning works on every product

The client SHALL support a follow mode that keeps the stream open and prints lines as they
arrive, and SHALL exit cleanly on interrupt without implying anything happened to the
deployment.

In follow mode the client SHALL continue across a redeploy, because the user is watching an
application rather than a container, and a stream that ended silently when the application
restarted would read as the application having stopped.

The client SHALL be able to pin the read to a single release by its number, including a release
that failed and whose pods no longer exist, on a deployment of any product.

#### Scenario: Interrupting a follow

- **WHEN** the user interrupts a followed stream
- **THEN** the client exits without suggesting the deployment was affected

#### Scenario: A redeploy during a follow

- **WHEN** a new release becomes live while the user is following
- **THEN** the stream continues with the new release's output

#### Scenario: Reading a failed release

- **WHEN** the user asks for the log of a release that failed and was rolled back
- **THEN** that release's output is printed

#### Scenario: Pinning on a curated product

- **WHEN** the user pins to a release of a deployment of a curated product
- **THEN** that release's output is printed

## REMOVED Requirements

### Requirement: Following is explicit, and following is the point

**Reason**: Its scenario for pinning on a product without release labels depended on a server answer that no longer exists.

**Migration**: Replaced by "Following is explicit, and pinning works on every product". The client's behavior for follow and pinning is unchanged.
