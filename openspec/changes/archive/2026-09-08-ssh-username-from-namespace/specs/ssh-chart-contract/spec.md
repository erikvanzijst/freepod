## MODIFIED Requirements

### Requirement: The tenant's namespace holds no credential for this feature
The chart MUST NOT render a password, a private key, or any registered user's public key into
the deployment's namespace. The only key material a deployment holds for SSH access is the
platform's public key, which the sidecar trusts, and the host key the sidecar generates for
itself at startup.

The keys that authenticate a person are resolved at the edge and never reach a tenant. The
account the edge authenticates to the sidecar as MUST be the Helm release name, and no product
MUST be able to choose a different one: the edge derives it from the deployment's own record
and reads no cluster object, so a chart free to name it otherwise would produce a deployment
the edge cannot log in to.

That account is not the username a person types. Which deployment a connection opens is
decided at the edge from an identifier the tenant's namespace does not hold and MUST NOT need
to hold; the chart's obligation ends at rendering the account the edge will present. A change
to the identifier clients present therefore MUST NOT require any chart to be re-rendered.

#### Scenario: No password exists
- **WHEN** the chart is rendered or installed
- **THEN** no password is generated or stored, and password authentication is unavailable

#### Scenario: No user keys reach the tenant namespace
- **WHEN** a deployment's namespace is inspected
- **THEN** it contains no registered user's public key and no private key

#### Scenario: The login account is the release name
- **WHEN** any product's chart is rendered
- **THEN** the account the edge authenticates as is the Helm release name, and no product
  overrides it

#### Scenario: The client-facing identifier appears nowhere in the release
- **WHEN** a deployment's rendered release is inspected
- **THEN** nothing in it records the username a client presents to reach this deployment
