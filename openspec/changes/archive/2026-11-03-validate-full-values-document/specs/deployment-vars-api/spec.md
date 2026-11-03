## MODIFIED Requirements

### Requirement: A validation failure never echoes the submitted value
An error returned for an invalid var, or for chart values and vars that together fail
the template's whole schema, and any log line recording it, SHALL identify the var by
key and by the constraint it failed, and MUST NOT include any var's value or any part
of it.

Schema validation libraries conventionally embed the offending instance in their error
message; that message reaches both the caller and the log aggregator, so it MUST NOT be
propagated for vars, nor for any document that contains them.

#### Scenario: A sensitive var fails validation
- **WHEN** a caller sets a sensitive var to a value the schema rejects
- **THEN** the error names the key and the failed constraint
- **AND** neither the response nor any log line contains the submitted value

#### Scenario: A sensitive var fails a rule spanning both halves
- **WHEN** a schema's root conditional constrains a sensitive var given a chart value
- **AND** a caller submits a value that conditional rejects
- **THEN** the error names the key and the failed constraint
- **AND** neither the response, any log line, nor the raised exception's chain contains
  the submitted value
