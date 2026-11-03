## 1. Reading the eviction

- [x] 1.1 Add `read_eviction` to `BuildJobClient` and `KubectlBuildJobClient`, returning the pod's message when `status.reason` is `Evicted`, and verify tests for an evicted pod and for pods that failed otherwise
- [x] 1.2 Name the `work` and `buildkit` volumes once (`WORK_VOLUME`, `BUILDKIT_VOLUME`) and use the names in the Job manifest (design D2)

## 2. Explaining it to the tenant

- [x] 2.1 Add `eviction_log_line`, matching the kubelet's emptyDir, container-limit, pod-limit, node-low and node-condition formats (design D1), and verify a test per format that the line names the limit and none of the node's internals
- [x] 2.2 Append the line to a failed build's log when its pod was evicted, keeping the gate line's precedence (design D3), and verify tests for the appended line and for gate precedence
- [x] 2.3 Log the kubelet's raw message as the worker's failure reason
- [x] 2.4 Run the full `api/` suite
