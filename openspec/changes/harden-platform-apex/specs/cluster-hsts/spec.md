## ADDED Requirements

### Requirement: Responses carry no Clear-Site-Data

The shared `headers-hsts` middleware SHALL remove any `Clear-Site-Data` header
from responses served over the `websecure` entrypoint. Its `"cookies"` value
applies beyond the host that sends it.

#### Scenario: An app sends Clear-Site-Data

- **WHEN** an app served over HTTPS answers with `Clear-Site-Data: "cookies"`
- **THEN** the response that reaches the browser carries no `Clear-Site-Data`
  header
