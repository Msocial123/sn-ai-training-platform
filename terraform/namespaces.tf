############################################################################
# Multi-tenant isolation: one namespace per participant, each with its own
# RBAC Role/RoleBinding, ResourceQuota, LimitRange, ServiceAccount + token,
# and a ready-to-use kubeconfig written out locally. This is the "break
# things and learn" boundary -- a participant can crash/delete/scale-to-zero
# everything in their own namespace and nothing else is affected.
############################################################################

locals {
  participants = { for i in range(1, var.participant_count + 1) :
    format("%02d", i) => "${var.participant_namespace_prefix}-${format("%02d", i)}"
  }
}

resource "kubernetes_namespace" "participant" {
  for_each = local.participants

  metadata {
    name = each.value
    labels = {
      "training/participant" = each.key
      "training/cohort"      = var.project_name
    }
  }

  depends_on = [module.eks]
}

resource "kubernetes_resource_quota" "participant" {
  for_each = local.participants

  metadata {
    name      = "${each.value}-quota"
    namespace = kubernetes_namespace.participant[each.key].metadata[0].name
  }

  spec {
    hard = {
      "requests.cpu"    = var.participant_cpu_quota
      "requests.memory" = var.participant_memory_quota
      "limits.cpu"      = var.participant_cpu_quota
      "limits.memory"   = var.participant_memory_quota
      "pods"            = tostring(var.participant_pod_quota)
    }
  }
}

resource "kubernetes_limit_range" "participant" {
  for_each = local.participants

  metadata {
    name      = "${each.value}-limits"
    namespace = kubernetes_namespace.participant[each.key].metadata[0].name
  }

  spec {
    limit {
      type = "Container"
      default = {
        cpu    = "500m"
        memory = "512Mi"
      }
      default_request = {
        cpu    = "100m"
        memory = "128Mi"
      }
    }
  }
}

resource "kubernetes_service_account" "participant" {
  for_each = local.participants

  metadata {
    name      = "${each.value}-sa"
    namespace = kubernetes_namespace.participant[each.key].metadata[0].name
  }
}

# Full control WITHIN their own namespace only -- deploy, scale, crash,
# delete, port-forward, view logs. Nothing cluster-scoped, nothing in any
# other namespace.
resource "kubernetes_role" "participant" {
  for_each = local.participants

  metadata {
    name      = "${each.value}-full-access"
    namespace = kubernetes_namespace.participant[each.key].metadata[0].name
  }

  rule {
    api_groups = ["", "apps", "batch", "autoscaling", "networking.k8s.io", "policy"]
    resources  = ["*"]
    verbs      = ["*"]
  }
  rule {
    api_groups = [""]
    resources  = ["pods/log", "pods/exec", "pods/portforward"]
    verbs      = ["*"]
  }
}

resource "kubernetes_role_binding" "participant" {
  for_each = local.participants

  metadata {
    name      = "${each.value}-full-access-binding"
    namespace = kubernetes_namespace.participant[each.key].metadata[0].name
  }

  role_ref {
    api_group = "rbac.authorization.k8s.io"
    kind      = "Role"
    name      = kubernetes_role.participant[each.key].metadata[0].name
  }

  subject {
    kind      = "ServiceAccount"
    name      = kubernetes_service_account.participant[each.key].metadata[0].name
    namespace = kubernetes_namespace.participant[each.key].metadata[0].name
  }
}

# Kubernetes 1.24+ no longer auto-creates a token Secret for a ServiceAccount
# -- this creates one explicitly and waits for the token controller to
# populate it.
resource "kubernetes_secret_v1" "participant_token" {
  for_each = local.participants

  metadata {
    name      = "${each.value}-sa-token"
    namespace = kubernetes_namespace.participant[each.key].metadata[0].name
    annotations = {
      "kubernetes.io/service-account.name" = kubernetes_service_account.participant[each.key].metadata[0].name
    }
  }

  type                           = "kubernetes.io/service-account-token"
  wait_for_service_account_token = true
}

# One kubeconfig file per participant, scoped to only their namespace's
# ServiceAccount token. Hand these out individually -- e.g.
# kubeconfigs/participant-07.yaml goes only to participant 07.
resource "local_sensitive_file" "participant_kubeconfig" {
  for_each = local.participants

  filename = "${path.module}/kubeconfigs/${each.value}.yaml"
  content = templatefile("${path.module}/templates/kubeconfig.tpl", {
    cluster_name     = module.eks.cluster_name
    cluster_endpoint = module.eks.cluster_endpoint
    cluster_ca       = module.eks.cluster_certificate_authority_data
    namespace        = each.value
    token            = kubernetes_secret_v1.participant_token[each.key].data["token"]
  })
}
