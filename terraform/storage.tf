# The EBS CSI driver addon is installed (eks.tf), but nothing marks a
# StorageClass as default -- the cluster only has the legacy in-tree "gp2"
# class (kubernetes.io/aws-ebs), which doesn't work on modern EKS nodes.
# Any PVC without an explicit storageClassName (Loki, Grafana, participant
# workloads, etc.) would otherwise sit Pending forever.
resource "kubernetes_storage_class_v1" "gp3_default" {
  metadata {
    name = "gp3"
    annotations = {
      "storageclass.kubernetes.io/is-default-class" = "true"
    }
  }

  storage_provisioner    = "ebs.csi.aws.com"
  reclaim_policy         = "Delete"
  volume_binding_mode    = "WaitForFirstConsumer"
  allow_volume_expansion = true

  parameters = {
    type      = "gp3"
    encrypted = "true"
  }

  depends_on = [module.eks]
}
