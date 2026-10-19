output "apex_headers_middleware" {
  description = "Traefik provider reference to the apex response-headers Middleware, for Ingresses in other namespaces."
  value       = "${var.namespace}-${kubernetes_manifest.apex_headers.manifest.metadata.name}@kubernetescrd"
}
