resource "kubernetes_namespace" "caelus" {
  metadata {
    name = local.ns_caelus

    labels = {
      name        = local.ns_caelus
      environment = local.environment
    }
  }
}

resource "kubernetes_namespace" "login" {
  metadata {
    name = local.is_prod_workspace ? "login" : "login-dev"
  }
}

# Where per-build Jobs run. This is the one namespace in the platform that
# executes untrusted tenant code, and — uncomfortably but correctly — it is
# also the one that must NOT be under a restrictive Pod Security Standard.
#
# Rootless BuildKit needs to create a user namespace and mount inside it, which
# the container's own seccomp and AppArmor profiles block. Lifting them
# requires setting both profiles to `Unconfined` on the pod, and Pod Security
# `baseline` explicitly forbids that (it bans an explicit Unconfined seccomp
# profile and any AppArmor override). So `privileged` is the only level under
# which a build pod can be admitted at all.
#
# `privileged` here is a statement about *admission*, not about the pod: build
# pods run as uid 1000, are not `privileged: true`, mount no host paths, and do
# not use host networking. What actually contains them is elsewhere and does
# not depend on PSA:
#
#   - rootless BuildKit, so nothing in the pod runs as real root on the node;
#   - a per-build pod lifetime, so `--oci-worker-no-process-sandbox` only ever
#     exposes that same tenant's own build processes;
#   - a NetworkPolicy that denies all ingress and every internal destination;
#   - no database, Kubernetes, or registry credential in the pod at all;
#   - resource limits, an activeDeadlineSeconds, and a bounded emptyDir.
#
# The label is set explicitly rather than left to the cluster default so that
# changing the cluster default cannot silently start rejecting every build.
resource "kubernetes_namespace" "builds" {
  metadata {
    name = local.ns_builds

    labels = {
      name        = local.ns_builds
      environment = local.environment

      "pod-security.kubernetes.io/enforce"         = "privileged"
      "pod-security.kubernetes.io/enforce-version" = "latest"
    }
  }
}

# The tenant registry's own namespace rather than the platform's, so the builds
# policy's "never reach the platform namespace" needs no exception (D4 of
# authenticated-tenant-registry). `restricted`: the registry runs non-root
# with nothing to lift.
resource "kubernetes_namespace" "registry" {
  metadata {
    name = local.ns_registry

    labels = {
      name        = local.ns_registry
      environment = local.environment

      "pod-security.kubernetes.io/enforce"         = "restricted"
      "pod-security.kubernetes.io/enforce-version" = "latest"
    }
  }
}

resource "kubernetes_namespace" "sshpiper" {
  metadata {
    name = local.ns_sshpiper

    labels = {
      name        = local.ns_sshpiper
      environment = local.environment
    }
  }
}
