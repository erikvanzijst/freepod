## Why

When the kubelet evicts a build pod, the build fails with nothing in its log
to say why. The most common cause is a build outgrowing its own storage
bound: BuildKit's state lives in a size-limited emptyDir, and a large
dependency install (a machine-learning framework, say) passes it. The tenant
sees their output stop mid-install and the status turn `failed`. An agent
driving `freepod deploy` sees the same thing and can only guess, so it retries
the identical build. The reason is recorded on the pod's status, but only the
worker's own log line ("Job terminated unsuccessfully") ever mentions the
failure.

## What Changes

- The build Job client reads the pod's eviction (`status.reason: Evicted` and
  the kubelet's message) when a Job fails.
- The build worker appends one line to the failed build's log saying why it
  was stopped, in the tenant's terms:
  - outgrowing BuildKit's storage names the limit and says to install less;
  - outgrowing the working copy names its limit;
  - outgrowing the build's total disk allowance names that limit;
  - the node running short of resources, or refusing the pod outright, is a
    platform problem and the line says to start the build again.
- The kubelet's raw message is logged by the worker only. It names node
  thresholds and other tenants' containers, which never reach a tenant.
- A gate failure keeps priority: it is the more specific explanation for a
  pod that never ran its build.

## Capabilities

### New Capabilities

### Modified Capabilities

- `build-worker`: a failed Job whose pod was evicted gets a log line
  explaining the eviction.

## Impact

- `api/app/services/build_jobs.py`: `read_eviction` on `BuildJobClient` and
  `KubectlBuildJobClient`; volume name constants shared with the worker.
- `api/app/build_worker.py`: `eviction_log_line` and the failed-Job branch.
- No API, schema, or client change: the line arrives through the existing
  build log, which `freepod deploy` already streams to the end.
