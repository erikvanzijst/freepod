output "namespace" {
  description = "Kubernetes namespace"
  value       = var.namespace
}

output "api_service_name" {
  description = "API Kubernetes service name"
  value       = kubernetes_service.api.metadata[0].name
}

output "ui_service_name" {
  description = "UI Kubernetes service name"
  value       = kubernetes_service.ui.metadata[0].name
}

output "ingress_host" {
  description = "External hostname"
  value       = var.domain
}

output "api_endpoint" {
  description = "Full API endpoint URL"
  value       = "https://${var.domain}/api"
}

# Consumed by tf/app/sshpiper, which assembles the resolver's DATABASE_URL from
# it. The role is created here because it lives in the platform database; the
# process that uses it runs in the SSH edge's namespace, which cannot read a
# Secret from this one.
output "ssh_resolver_db_password" {
  description = "Password for the caelus_ssh_resolver read-only role"
  value       = random_password.ssh_resolver_db.result
  sensitive   = true
}

output "ssh_resolver_db_role" {
  description = "Role name the SSH auth resolver connects as"
  value       = "caelus_ssh_resolver"
}

output "database_host" {
  description = "In-cluster hostname of the platform database"
  value       = "caelus-postgres.${var.namespace}.svc.cluster.local"
}

output "database_name" {
  description = "Platform database name"
  value       = var.db_name
}

# Consumed by tf/app/app-auth, for the same reason as the SSH resolver's.
output "app_auth_db_password" {
  description = "Password for the caelus_app_auth role"
  value       = random_password.app_auth_db.result
  sensitive   = true
}

output "app_auth_db_role" {
  description = "Role name the app authentication service connects as"
  value       = "caelus_app_auth"
}
