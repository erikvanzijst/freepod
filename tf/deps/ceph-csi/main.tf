resource "helm_release" "ceph_csi_rbd" {
  name      = "ceph-csi-rbd"
  namespace = var.namespace
  # Direct .tgz URL for the reason in ../prometheus/prometheus.tf.
  # Releases: https://github.com/ceph/ceph-csi/releases
  chart = "https://ceph.github.io/csi-charts/rbd/ceph-csi-rbd-3.18.2.tgz"

  values = [
    yamlencode({
      csiConfig = [{
        clusterID = var.cluster_id
        monitors  = var.monitors
      }]

      # Every node that can run a pod with a volume needs the node plugin,
      # including the tainted tenant pool.
      nodeplugin = {
        tolerations = [{ operator = "Exists" }]
      }

      # The chart's required anti-affinity places one replica per node, and
      # only one node is untainted.
      provisioner = {
        replicaCount = 1
      }

      # Classes and their credentials are declared below, one per pool.
      storageClass = { create = false }
      secret       = { create = false }
    })
  ]
}

resource "kubernetes_secret_v1" "pool" {
  for_each = var.storage_classes

  metadata {
    name      = "csi-rbd-${each.value.pool}"
    namespace = var.namespace
  }

  data = {
    userID  = each.value.user_id
    userKey = var.user_keys[each.value.user_id]
  }
}

resource "kubernetes_storage_class_v1" "pool" {
  for_each = var.storage_classes

  metadata {
    name = each.key
  }

  storage_provisioner    = "rbd.csi.ceph.com"
  reclaim_policy         = each.value.reclaim_policy
  allow_volume_expansion = true
  volume_binding_mode    = "Immediate"
  # Freed blocks go back to the pool, and from there to the SSDs.
  mount_options = ["discard"]

  parameters = {
    clusterID                   = var.cluster_id
    pool                        = each.value.pool
    imageFeatures               = "layering,exclusive-lock,object-map,fast-diff"
    "csi.storage.k8s.io/fstype" = "ext4"

    "csi.storage.k8s.io/provisioner-secret-name"            = kubernetes_secret_v1.pool[each.key].metadata[0].name
    "csi.storage.k8s.io/provisioner-secret-namespace"       = var.namespace
    "csi.storage.k8s.io/controller-expand-secret-name"      = kubernetes_secret_v1.pool[each.key].metadata[0].name
    "csi.storage.k8s.io/controller-expand-secret-namespace" = var.namespace
    "csi.storage.k8s.io/node-stage-secret-name"             = kubernetes_secret_v1.pool[each.key].metadata[0].name
    "csi.storage.k8s.io/node-stage-secret-namespace"        = var.namespace
  }

  depends_on = [helm_release.ceph_csi_rbd]
}

resource "helm_release" "snapshot_controller" {
  name      = "snapshot-controller"
  namespace = var.namespace
  chart     = "https://github.com/piraeusdatastore/helm-charts/releases/download/snapshot-controller-5.4.0/snapshot-controller-5.4.0.tgz"

  values = [yamlencode({ keepCRDs = true })]
}

resource "kubernetes_secret_v1" "snapshotter" {
  metadata {
    name      = "csi-rbd-snapshots"
    namespace = var.namespace
  }

  data = {
    userID  = var.snapshot_user_id
    userKey = var.user_keys[var.snapshot_user_id]
  }
}

# Velero uses one class per driver, so this class's client reaches every pool.
# Snapshots stay in their volume's pool.
resource "helm_release" "snapshot_class" {
  name      = "rbd-snapshot-class"
  namespace = var.namespace
  chart     = helm_release.snapshot_controller.chart

  values = [
    yamlencode({
      installCRDs = false
      controller  = { enabled = false }
      volumeSnapshotClasses = [{
        name           = "ceph-rbd"
        driver         = "rbd.csi.ceph.com"
        deletionPolicy = "Delete"
        labels         = { "velero.io/csi-volumesnapshot-class" = "true" }
        parameters = {
          clusterID                                         = var.cluster_id
          "csi.storage.k8s.io/snapshotter-secret-name"      = kubernetes_secret_v1.snapshotter.metadata[0].name
          "csi.storage.k8s.io/snapshotter-secret-namespace" = var.namespace
        }
      }]
    })
  ]

  depends_on = [helm_release.snapshot_controller, helm_release.ceph_csi_rbd]
}
