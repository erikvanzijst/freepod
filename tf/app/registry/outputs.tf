output "pod_labels" {
  description = "Labels selecting the registry pod, for the builds NetworkPolicy"
  value       = local.labels
}

output "cluster_ip" {
  value = kubernetes_service.registry.spec[0].cluster_ip
}
