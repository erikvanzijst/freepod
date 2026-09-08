output "namespace" {
  description = "Namespace holding the certificate store and every certificate it can name."
  value       = kubernetes_namespace.tls.metadata[0].name
}

output "wildcard_secret_name" {
  description = "Secret backing the store's default certificate."
  value       = local.wildcard_secret_name
}
