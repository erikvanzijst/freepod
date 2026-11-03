## Context

A build pod can be evicted by the kubelet for three kinds of reason: one of
its emptyDirs passed its `sizeLimit`, the pod or a container passed its
`ephemeral-storage` limit, or the node itself ran short (or refused the pod at
admission while under pressure). The Job has `backoffLimit: 0`, so any of
these fails it. The pod keeps `status.reason: Evicted` and the kubelet's
message until the Job's TTL reaps it, which is well past the worker's next
pass.

The egress gate already sets the pattern for platform-caused failures: the
worker appends a fixed, tenant-facing line to the stored log and keeps the
raw cause for its own log (see `build-execution`).

## Decisions

### D1: Translate the kubelet's message; never pass it through

The kubelet's message for node pressure carries the eviction threshold, the
node's available capacity, and the names and usage of *other* pods'
containers ("Container app was using …"). On a shared node those are other
tenants' workloads. So the tenant line is chosen by matching the message
against the four formats in `pkg/kubelet/eviction` (`emptyDirMessageFmt`,
`containerEphemeralStorageMessageFmt`, `podEphemeralStorageMessageFmt`,
`nodeLowMessageFmt`, plus `nodeConditionMessageFmt` for admission refusals),
and only the limit the build itself outgrew is carried into the line. An
unrecognized message gets a generic line rather than its text.

**Alternative rejected:** pass the message through after redacting numbers.
The formats are stable, but redaction would still leak container names, and a
generic line loses nothing a tenant can act on.

### D2: Name the volume's purpose, not the volume

`buildkit` and `work` are names only this codebase gives meaning to. The line
says "image layers and build cache" or "working copy of the project", because
that is what tells a tenant (or their agent) which part of the build to
shrink. The names become shared constants so the manifest and the
translation cannot drift apart.

### D3: Read the eviction only when the gate did not fail

An evicted gate pod is still a gate failure from the tenant's point of view:
the build never ran. Checking the gate first also keeps the extra `kubectl get
pods` off that path.

## Risks / Trade-offs

- [The kubelet rewords a message] → The line falls back to the generic "stopped
  by the platform" wording; the worker's log still carries the raw message, so
  the drift is visible to operators.
- [The pod is reaped before the worker looks] → The Job's TTL is an hour and the
  worker passes every few seconds, so the window only matters while the
  worker is down for an hour or more; the build then fails as it does today.
