# Spec Delta

## ADDED Requirements

### Requirement: Dashboard clients issue one-minute access tokens

The `freepod-prod` and `freepod-dev` clients SHALL issue access tokens that expire 60 seconds after issue, matching oauth2-proxy's refresh interval. Other clients SHALL keep the realm's access token lifespan.

#### Scenario: Dashboard token lifetime

- **WHEN** oauth2-proxy obtains tokens from `freepod-dev`
- **THEN** the access token expires 60 seconds after it was issued

#### Scenario: CLI clients unaffected

- **WHEN** a CLI client obtains an access token
- **THEN** its lifetime is the realm's, not 60 seconds
