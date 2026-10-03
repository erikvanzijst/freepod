## Purpose

Caelus is a multi-tenant platform: each user deployment runs as a Helm release in its own Kubernetes namespace on a shared cluster. This capability confines each deployment to the network it legitimately needs — its own namespace, cluster DNS, the shared mailer, and the public internet — while denying all other in-cluster, node, LAN, and cloud-metadata access, so that mutually untrusted tenants cannot reach one another or the platform's control plane. The isolation is owned and enforced by the platform (not by product charts or user values) and is paired with Pod Security Admission so it cannot be bypassed.

## Requirements

### Requirement: Baseline network isolation applied to every deployment namespace
The reconciler MUST apply a platform-owned baseline `NetworkPolicy` to each deployment's Kubernetes namespace. The policy MUST select all pods in the namespace and enable both `Ingress` and `Egress` policy types, establishing default-deny in both directions before any allow rule is evaluated. The policy MUST be applied as a platform-owned resource independent of the deployment's Helm release, so that it cannot be removed or overridden by chart content, chart upgrades, or user-supplied values.

#### Scenario: Baseline policy created on provision
- **WHEN** the reconciler applies a deployment
- **THEN** a `NetworkPolicy` named `caelus-tenant-baseline` exists in the deployment's namespace
- **AND** it selects all pods (empty pod selector) with policy types `Ingress` and `Egress`

#### Scenario: Policy is not part of the Helm release
- **WHEN** the deployment's Helm release is upgraded or reconciled
- **THEN** the baseline `NetworkPolicy` is managed by the platform, not the chart
- **AND** it is not removed or replaced by the chart's rendered manifests

### Requirement: Isolation applied before workload pods are created
The reconciler MUST apply the namespace isolation guardrails after ensuring the namespace exists and before installing or upgrading the deployment's Helm release, so that no workload pod ever runs before its NetworkPolicy jail exists.

#### Scenario: Ordering during reconcile apply
- **WHEN** the reconciler applies a deployment
- **THEN** it ensures the namespace exists, then applies tenant isolation, then performs the Helm install/upgrade, in that order

### Requirement: Tenant containers start only once egress isolation is enforced
A `NetworkPolicy` existing is not the same as it being enforced: the cluster's policy controller programs a new pod's rules asynchronously, after the pod has its address and its containers are running. The platform MUST therefore inject a gate into every pod template of a deployment's Helm release as the pod's first init container, so that none of the chart's own containers start until the baseline egress policy is enforced for that pod. The gate MUST be injected by the platform at render time, independent of chart content, so that no product chart, chart upgrade or user-supplied value can omit, reorder or replace it.

The gate MUST probe a destination that is always listening and that the baseline policy denies (the Kubernetes API server, through the address the kubelet supplies to every container), and MUST complete only after that destination has refused it at least twice in a row. If the destination is still reachable when the gate's deadline expires, the gate MUST fail, so that the pod does not start rather than starting unjailed.

#### Scenario: Every pod template carries the gate
- **WHEN** the reconciler installs or upgrades a deployment's Helm release
- **THEN** every rendered pod template (Deployment, StatefulSet, DaemonSet, Job, CronJob, Pod), including Helm hooks, has the gate as its first init container
- **AND** the rendered manifests are otherwise unchanged

#### Scenario: A chart cannot supply its own gate
- **WHEN** a chart renders an init container with the gate's name
- **THEN** it is replaced by the platform's gate

#### Scenario: The application starts after the jail
- **WHEN** a new pod starts in a deployment namespace while its egress rules are not yet programmed
- **THEN** the gate keeps running while the Kubernetes API server is reachable
- **AND** the pod's other containers start only after it has been refused

#### Scenario: The jail never arrives
- **WHEN** the Kubernetes API server is still reachable from a new pod when the gate's deadline expires
- **THEN** the gate exits non-zero and the pod's other containers do not start

### Requirement: Ingress restricted to the shared edge and the deployment's own namespace
The baseline policy MUST permit ingress only from the shared ingress controller (Traefik), from the platform SFTP router (sshpiper), and from pods within the same namespace. The ingress allowance for the shared edge MUST NOT restrict ports, so that products may expose their service on any port without per-product configuration. The ingress allowance for the SFTP router MUST be restricted to the SFTP sidecar port (2222/TCP) only. All other ingress MUST be denied.

#### Scenario: Ingress from the shared ingress controller is allowed
- **WHEN** the shared Traefik ingress controller connects to a pod in the deployment namespace
- **THEN** the connection is allowed on any port

#### Scenario: Ingress from the SFTP router is allowed on the sidecar port
- **WHEN** an sshpiper pod connects to a pod in the deployment namespace on port 2222/TCP
- **THEN** the connection is allowed

#### Scenario: Ingress from the SFTP router to other ports is denied
- **WHEN** an sshpiper pod connects to a pod in the deployment namespace on a port other than 2222
- **THEN** the connection is denied

#### Scenario: Intra-namespace ingress is allowed
- **WHEN** a pod in the deployment namespace connects to another pod in the same namespace
- **THEN** the connection is allowed

#### Scenario: Ingress from another deployment namespace is denied
- **WHEN** a pod in a different deployment namespace connects to a pod in the deployment namespace
- **THEN** the connection is denied

### Requirement: Egress permits only the deployment's own namespace, cluster DNS, the shared mailer, the shared database pooler, and the public internet
The baseline policy MUST permit egress to: pods within the same namespace; cluster DNS (kube-dns) on port 53 (UDP and TCP); the shared SMTP relay service; the shared database pooler on its client port; and the public internet. All other egress MUST be denied.

The pooler allowance is part of the single fleet-wide policy and is therefore present in every deployment namespace, including those whose product has no relational storage. Reachability is not authorization: a deployment without provisioned credentials cannot authenticate, and one deployment's credentials do not grant access to another's database.

#### Scenario: Intra-namespace egress is allowed
- **WHEN** a pod in the deployment namespace connects to another pod in the same namespace
- **THEN** the connection is allowed

#### Scenario: DNS egress is allowed
- **WHEN** a pod in the deployment namespace queries cluster DNS
- **THEN** the query to kube-dns on port 53 (UDP or TCP) is allowed

#### Scenario: Shared mailer egress is allowed
- **WHEN** a pod in the deployment namespace connects to the shared SMTP relay
- **THEN** the connection to the mailer service is allowed

#### Scenario: Database pooler egress is allowed
- **WHEN** a pod in the deployment namespace connects to the shared database pooler on its client port
- **THEN** the connection is allowed

#### Scenario: Pooler egress is allowed on the client port only
- **WHEN** a pod in the deployment namespace connects to the pooler on any other port
- **THEN** the connection is denied

#### Scenario: Pooler is reachable from a deployment without relational storage
- **WHEN** a pod belonging to a deployment whose product has no relational storage connects to the pooler
- **THEN** the connection is allowed at the network layer
- **AND** the deployment holds no credentials with which to authenticate

#### Scenario: Public internet egress is allowed
- **WHEN** a pod in the deployment namespace connects to a public (non-internal) address
- **THEN** the connection is allowed

### Requirement: Egress denies all internal networks and cloud metadata
The public-internet egress allowance MUST exclude every internal address range: the private ranges `10.0.0.0/8`, `172.16.0.0/12`, and `192.168.0.0/16`, and the link-local range `169.254.0.0/16`. As a result, a deployment MUST NOT be able to reach other deployments' pods or services, the cluster service network (including the Kubernetes API server), the cluster node, the LAN, or the cloud metadata endpoint, except via the explicit DNS, mailer, database pooler, and intra-namespace allowances.

The tenant PostgreSQL server itself is not among the allowances. A deployment MUST NOT be able to reach it directly, which is what makes the pooler the only path to a database.

#### Scenario: Cross-deployment traffic is denied
- **WHEN** a pod in the deployment namespace connects to a pod or service in another deployment's namespace
- **THEN** the connection is denied

#### Scenario: Kubernetes API server is unreachable
- **WHEN** a pod in the deployment namespace connects to the Kubernetes API server (via its cluster IP or the node address)
- **THEN** the connection is denied

#### Scenario: Node, LAN, and metadata endpoint are unreachable
- **WHEN** a pod in the deployment namespace connects to the cluster node IP, another LAN host, or the link-local metadata endpoint `169.254.169.254`
- **THEN** the connection is denied

#### Scenario: The tenant PostgreSQL server is unreachable directly
- **WHEN** a pod in the deployment namespace connects to the tenant PostgreSQL server rather than the pooler
- **THEN** the connection is denied

### Requirement: Pod Security Admission enforced on deployment namespaces
The reconciler MUST label each deployment namespace to enforce the Pod Security Admission `baseline` profile, so that workloads cannot bypass the NetworkPolicy by joining the host network namespace (`hostNetwork`) or otherwise escaping pod-network filtering (`hostPort`, `hostPath`, privileged containers). The reconciler MUST also apply a label marking the namespace as a Caelus tenant so shared services and cluster-wide policy can select tenant namespaces.

#### Scenario: Namespace enforces the baseline profile
- **WHEN** the reconciler applies tenant isolation to a namespace
- **THEN** the namespace carries the label `pod-security.kubernetes.io/enforce: baseline`
- **AND** the namespace carries the tenant marker label `caelus.dev/tenant: "true"`

#### Scenario: hostNetwork workload is rejected
- **WHEN** a pod requesting `hostNetwork: true` is submitted to a deployment namespace
- **THEN** the Kubernetes API server rejects the pod with a Pod Security violation

### Requirement: Isolation is idempotent and re-applicable across the fleet
Applying tenant isolation MUST be idempotent: re-applying the labels and policy MUST be a no-op when nothing has changed, and MUST converge the namespace to the desired policy when it has drifted. The policy MUST use a stable name so re-application updates it in place rather than creating duplicates. The platform MUST provide an administrative operation that re-applies the current baseline policy and labels across all running deployment namespaces without modifying their Helm releases; because NetworkPolicy changes reprogram the network dataplane without restarting pods, this operation MUST be non-disruptive to running workloads.

#### Scenario: Re-applying isolation is a no-op
- **WHEN** tenant isolation is applied to a namespace that already has the current baseline policy and labels
- **THEN** the policy and labels are unchanged and no workload is disrupted

#### Scenario: Fleet-wide policy sync
- **WHEN** an administrator runs the network-policy sync operation
- **THEN** the current baseline policy and labels are re-applied to every active (non-deleted) deployment namespace
- **AND** the deployments' Helm releases are not modified
- **AND** per-namespace failures are reported without aborting the remaining namespaces

### Requirement: Isolation resources are removed with the namespace
The baseline `NetworkPolicy` MUST be namespaced to the deployment's namespace, so that deleting the deployment's namespace removes the policy as part of the standard teardown, with no separate deletion step.

#### Scenario: Policy removed on deployment delete
- **WHEN** a deployment is deleted and its namespace is removed
- **THEN** the baseline `NetworkPolicy` is removed together with the namespace

### Requirement: Cluster-specific isolation inputs are configurable
The cluster-specific inputs to the baseline policy MUST be configurable rather than hard-coded, including: the baseline policy name, the ingress controller's namespace and pod label, the SFTP router's namespace, pod label, and sidecar port, the shared mailer's namespace, pod label, and port, the cluster DNS service IP, and the list of internal CIDR ranges excluded from public-internet egress. Configuration MUST provide defaults that match the current cluster.

#### Scenario: Overriding a cluster-specific input
- **WHEN** an operator overrides an isolation input (for example, the mailer namespace or an excluded CIDR range) via settings
- **THEN** the rendered baseline policy reflects the overridden value

#### Scenario: Overriding the SFTP router selector
- **WHEN** an operator overrides the SFTP router's namespace, pod label, or sidecar port via settings
- **THEN** the rendered baseline policy's SFTP ingress rule reflects the overridden values
