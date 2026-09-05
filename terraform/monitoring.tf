############################################################################
# ONE monitoring stack for the entire cluster (not per-participant). Every
# namespace's metrics flow in here via cluster-wide Prometheus scraping, so
# when a participant "breaks" their namespace, only their own Grafana panels
# go red -- the stack itself is shared infrastructure, not part of the
# break/learn surface.
############################################################################

resource "random_password" "grafana_admin" {
  length  = 20
  special = false
}

resource "kubernetes_namespace" "monitoring" {
  count = var.enable_monitoring ? 1 : 0

  metadata {
    name = "monitoring"
    labels = {
      "training/purpose" = "shared-monitoring"
    }
  }

  depends_on = [module.eks]
}

resource "helm_release" "kube_prometheus_stack" {
  count = var.enable_monitoring ? 1 : 0

  name       = "kube-prometheus-stack"
  repository = "https://prometheus-community.github.io/helm-charts"
  chart      = "kube-prometheus-stack"
  namespace  = kubernetes_namespace.monitoring[0].metadata[0].name
  version    = "65.5.0"

  values = [yamlencode({
    # Pin the whole stack to the small, fixed system node group -- it's
    # shared cluster infrastructure and shouldn't land on (or be evicted
    # from) an ephemeral Karpenter-provisioned participant node.
    grafana = {
      adminPassword = random_password.grafana_admin.result
      service = {
        type = var.grafana_service_type
      }
      nodeSelector = { role = "system" }
    }
    prometheus = {
      prometheusSpec = {
        # Scrape every namespace cluster-wide, participant namespaces included.
        podMonitorSelectorNilUsesHelmValues     = false
        serviceMonitorSelectorNilUsesHelmValues = false
        ruleSelectorNilUsesHelmValues           = false
        retention                               = "7d"
        nodeSelector                            = { role = "system" }
      }
    }
    alertmanager = {
      enabled = true
      alertmanagerSpec = {
        nodeSelector = { role = "system" }
      }
    }
    prometheusOperator = {
      nodeSelector = { role = "system" }
    }
    kube-state-metrics = {
      nodeSelector = { role = "system" }
    }
    nodeExporter = {
      # DaemonSet -- must run everywhere, including participant nodes, to
      # actually collect their metrics. No nodeSelector here on purpose.
      enabled = true
    }
  })]

  depends_on = [module.eks]
}
