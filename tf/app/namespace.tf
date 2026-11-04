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
# executes untrusted tenant code.
#
# Rootless BuildKit needs to create a user namespace and mount inside it. In the
# gVisor sandbox (local.build_runtime_class) the sandbox handles both itself, so
# build pods keep their default seccomp and AppArmor profiles and the namespace
# runs under `baseline`. `restricted` is out of reach: BuildKit's newuidmap
# needs privilege escalation. On the default runtime, lifting the profiles
# requires `Unconfined`, which `baseline` forbids, so the namespace is
# `privileged`.
#
# Either way that is a statement about *admission*, not about the pod: build
# pods run as uid 1000, are not `privileged: true`, mount no host paths, and do
# not use host networking. What else contains them does not depend on PSA:
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

      "pod-security.kubernetes.io/enforce"         = local.build_runtime_class == "" ? "privileged" : "baseline"
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

resource "kubernetes_namespace" "garage" {
  metadata {
    name = local.ns_garage

    labels = {
      name        = local.ns_garage
      environment = local.environment
    }
  }
}
