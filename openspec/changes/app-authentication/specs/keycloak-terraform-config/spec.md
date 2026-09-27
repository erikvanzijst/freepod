## ADDED Requirements

### Requirement: App-authentication clients per environment

The `freepod` realm SHALL declare one OpenID Connect client per environment for the app authentication broker: `freepod-apps-prod` and `freepod-apps-dev`. Each client SHALL:
- be confidential;
- enable only the standard (authorization code) flow, with PKCE method `S256`;
- disable the implicit flow, direct access grants and service accounts;
- list exactly one valid redirect URI: its environment's broker callback on `login.freepod.eu` or `login.dev.freepod.eu`.

Neither client SHALL use a wildcard redirect URI. Neither SHALL require identity-provider consent, because the broker asks for consent per app itself. The number of clients SHALL NOT grow with the number of deployments.

The broker's client ID and secret SHALL reach `tf/app` the same way the existing client credentials do: as maps keyed by workspace name, supplied through the gitignored `secrets.auto.tfvars`.

#### Scenario: Clients exist per environment

- **WHEN** the realm's clients are inspected
- **THEN** `freepod-apps-prod` and `freepod-apps-dev` exist alongside the existing clients

#### Scenario: Single fixed redirect URI

- **WHEN** the redirect URIs of `freepod-apps-prod` are inspected
- **THEN** there is exactly one, on `https://login.freepod.eu`, and it contains no wildcard

#### Scenario: New deployments need no identity-provider change

- **WHEN** a thousand `custom` deployments enable authentication
- **THEN** the realm still has exactly two app-authentication clients

#### Scenario: Workspace selects its client

- **WHEN** `tf/app` is applied in the `prod` workspace
- **THEN** the broker is configured with the `freepod-apps-prod` client ID and secret
