variable "namespace" {
  description = "Namespace for the sshpiperd deployment (workspace-scoped)"
  type        = string
}

variable "ssh_port" {
  description = "Cluster-side SSH port bound on the node via klipper ServiceLB (2222 prod, 2223 dev)"
  type        = number
}

variable "sshpiper_image" {
  description = "sshpiperd image; keep the tag in sync with the Pipe CRD vendored in tf/deps/sshpiper"
  type        = string
  default     = "farmer1992/sshpiperd:v1.5.4"
}

variable "rbac_name" {
  description = "Name for the cluster-scoped RBAC objects (must be unique per environment)"
  type        = string
}

variable "sshpiper_host_private_key" {
  description = "OpenSSH private key the edge authenticates to every SFTP sidecar with. One per environment; see tf/app/variables.tf."
  type        = string
  sensitive   = true
}

variable "upstream_private_key" {
  description = "OpenSSH private key the edge authenticates to every SFTP sidecar with. One per environment; see tf/app/variables.tf."
  type        = string
  sensitive   = true
}

variable "resolver_image" {
  description = "Daemons image the SSH auth resolver runs from (/ssh-auth), pinned to an immutable version"
  type        = string
}

variable "resolver_database_url" {
  description = "libpq URL for the read-only caelus_ssh_resolver role. NOT SQLAlchemy's postgresql+psycopg:// form, which pgx rejects."
  type        = string
  sensitive   = true
}

variable "resolver_port" {
  description = "Loopback port the resolver serves gRPC on, inside the edge's own pod"
  type        = number
  default     = 50051
}
