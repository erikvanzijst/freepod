## ADDED Requirements

### Requirement: Only the studio's own origin may frame it
The studio's Ingress SHALL answer every response with
`X-Frame-Options: SAMEORIGIN`, through a Middleware of the chart's own, so the
chrome can frame opencode from the studio's origin and no other origin can
frame either. The preview's Ingress SHALL NOT carry it.

#### Scenario: The studio Ingress refuses other origins' frames
- **WHEN** the chart is rendered with an ingress host
- **THEN** `<release>-ingress` lists `<release>-frame-self`, which sets `X-Frame-Options: SAMEORIGIN`
- **AND** `<release>-preview` does not list it
