# Spec Delta

## ADDED Requirements

### Requirement: Container usage covers sandboxed containers

The system SHALL collect per-container CPU usage
(`container_cpu_usage_seconds_total`) and memory working set
(`container_memory_working_set_bytes`) from the kubelet's resource metrics,
which report containers in a gVisor sandbox. It SHALL keep exactly one
container-level series of each per container, so usage is not double-counted.

#### Scenario: Sandboxed container under load

- **WHEN** a container in a gVisor sandbox uses CPU and memory
- **THEN** both metrics report that container's actual usage, not zero

#### Scenario: Container on the default runtime

- **WHEN** a runc container is scraped
- **THEN** both metrics report the same values cAdvisor reports for it

#### Scenario: One series per container

- **WHEN** usage is queried for one container by namespace, pod and container
- **THEN** exactly one container-level series exists for each of the two
  metrics
