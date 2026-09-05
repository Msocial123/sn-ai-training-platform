############################################################################
# Karpenter: dynamically provisions/terminates EC2 nodes for PARTICIPANT
# WORKLOADS ONLY, based on actual unschedulable-pod pressure -- no static
# ASG size to babysit. The IAM side (controller role, node role, SQS
# interruption queue, access entry) is created by module.karpenter in
# eks.tf. This file installs the controller and the two CRs that tell it
# what/how to launch: EC2NodeClass (network/security/AMI) and NodePool
# (instance types, capacity type, and the 1->30-node resource ceiling).
############################################################################

resource "kubernetes_namespace" "karpenter" {
  metadata {
    name = "karpenter"
  }

  depends_on = [module.eks]
}

resource "helm_release" "karpenter" {
  name       = "karpenter"
  namespace  = kubernetes_namespace.karpenter.metadata[0].name
  repository = "oci://public.ecr.aws/karpenter"
  chart      = "karpenter"
  version    = "1.0.6"

  values = [yamlencode({
    settings = {
      clusterName       = module.eks.cluster_name
      clusterEndpoint   = module.eks.cluster_endpoint
      interruptionQueue = module.karpenter.queue_name
    }
    serviceAccount = {
      name = "karpenter"
      annotations = {
        "eks.amazonaws.com/role-arn" = module.karpenter.iam_role_arn
      }
    }
    # System node group only has 1-3 small nodes -- keep the controller
    # itself light so it always has room to schedule there.
    replicas = 1
    resources = {
      requests = { cpu = "250m", memory = "256Mi" }
      limits   = { memory = "512Mi" }
    }
    # Only ever schedule the controller on the fixed system node group,
    # never on a node Karpenter itself just provisioned.
    nodeSelector = {
      role = "system"
    }
  })]

  depends_on = [module.eks, module.karpenter]
}

# --- EC2NodeClass + NodePool -----------------------------------------------
# Applied via a plain `kubectl apply` after the Karpenter CRDs exist,
# instead of the Kubernetes provider's kubernetes_manifest resource --
# kubernetes_manifest needs the CRD present at *plan* time, which doesn't
# work in a first-ever apply where the Helm release creating the CRD and
# the manifest using it are in the same run. This avoids that chicken/egg
# problem entirely.

resource "local_file" "karpenter_ec2nodeclass" {
  filename = "${path.module}/generated/karpenter-ec2nodeclass.yaml"
  content = yamlencode({
    apiVersion = "karpenter.k8s.aws/v1"
    kind       = "EC2NodeClass"
    metadata   = { name = "default" }
    spec = {
      amiFamily = "AL2023"
      # Karpenter v1 API requires amiSelectorTerms explicitly -- "al2023@latest"
      # resolves to the newest AL2023 EKS-optimized AMI via SSM, same as
      # amiFamily alone used to do implicitly in pre-v1 API versions.
      amiSelectorTerms = [
        { alias = "al2023@latest" }
      ]
      role = module.karpenter.node_iam_role_name
      subnetSelectorTerms = [
        for id in module.vpc.private_subnets : { id = id }
      ]
      securityGroupSelectorTerms = [
        { id = module.eks.node_security_group_id }
      ]
      tags = merge(var.tags, {
        "karpenter.sh/discovery" = var.cluster_name
      })
    }
  })
}

resource "local_file" "karpenter_nodepool" {
  filename = "${path.module}/generated/karpenter-nodepool.yaml"
  content = yamlencode({
    apiVersion = "karpenter.sh/v1"
    kind       = "NodePool"
    metadata   = { name = "participants" }
    spec = {
      template = {
        metadata = {
          labels = { role = "participant-workload" }
        }
        spec = {
          nodeClassRef = {
            group = "karpenter.k8s.aws"
            kind  = "EC2NodeClass"
            name  = "default"
          }
          requirements = [
            { key = "kubernetes.io/arch", operator = "In", values = ["amd64"] },
            { key = "kubernetes.io/os", operator = "In", values = ["linux"] },
            # Karpenter's real offering values are "on-demand" / "spot"
            # (hyphenated) -- not the AWS API's "ON_DEMAND" style used
            # elsewhere in this project, so this is translated explicitly
            # rather than just lower()'d.
            { key = "karpenter.sh/capacity-type", operator = "In", values = [var.node_capacity_type == "SPOT" ? "spot" : "on-demand"] },
            { key = "node.kubernetes.io/instance-type", operator = "In", values = var.karpenter_node_instance_types },
          ]
        }
      }
      limits = {
        # Approximates a node_max_size (30) node ceiling: 2 vCPU / 4GiB
        # per t3.medium-class node * 30. Karpenter enforces this as a
        # resource limit rather than a literal node count -- that's how
        # the NodePool API works -- but it's the same practical cap.
        cpu    = tostring(var.node_max_size * 2)
        memory = "${var.node_max_size * 4}Gi"
      }
      disruption = {
        consolidationPolicy = "WhenEmptyOrUnderutilized"
        consolidateAfter    = "5m"
      }
    }
  })
}

# Dedicated NodePool for self-hosted LLM inference (Ollama, qwen3.8:27b --
# needs ~18GB just for model weights). Tainted so ONLY a pod with the
# matching toleration lands here -- this is a large, non-cheap node
# (r5.2xlarge: 8 vCPU / 64GiB, ~$0.50/hr on-demand in this region) and
# must not be consumed by ordinary participant/system workloads, the way
# the untainted "participants" NodePool above is.
resource "local_file" "karpenter_nodepool_llm" {
  filename = "${path.module}/generated/karpenter-nodepool-llm.yaml"
  content = yamlencode({
    apiVersion = "karpenter.sh/v1"
    kind       = "NodePool"
    metadata   = { name = "llm-inference" }
    spec = {
      template = {
        metadata = {
          labels = { role = "llm-inference" }
        }
        spec = {
          nodeClassRef = {
            group = "karpenter.k8s.aws"
            kind  = "EC2NodeClass"
            name  = "default"
          }
          taints = [
            { key = "llm-inference", value = "true", effect = "NoSchedule" }
          ]
          requirements = [
            { key = "kubernetes.io/arch", operator = "In", values = ["amd64"] },
            { key = "kubernetes.io/os", operator = "In", values = ["linux"] },
            { key = "karpenter.sh/capacity-type", operator = "In", values = ["on-demand"] },
            { key = "node.kubernetes.io/instance-type", operator = "In", values = ["r5.2xlarge"] },
          ]
        }
      }
      limits = {
        # One node's worth -- this pool is for a single Ollama instance,
        # not a scaling fleet.
        cpu    = "8"
        memory = "64Gi"
      }
      disruption = {
        # Slower to consolidate away than the participant pool -- an 18GB
        # model pull is expensive to repeat, so don't tear this node down
        # just because it was briefly idle.
        consolidationPolicy = "WhenEmptyOrUnderutilized"
        consolidateAfter    = "30m"
      }
    }
  })
}

resource "null_resource" "karpenter_crs" {
  triggers = {
    ec2nodeclass_sha = local_file.karpenter_ec2nodeclass.content_sha256
    nodepool_sha     = local_file.karpenter_nodepool.content_sha256
    nodepool_llm_sha = local_file.karpenter_nodepool_llm.content_sha256
    cluster          = module.eks.cluster_name
  }

  provisioner "local-exec" {
    interpreter = ["bash", "-c"]
    command     = <<-EOT
      set -euo pipefail
      aws eks update-kubeconfig --name "${module.eks.cluster_name}" --region "${var.aws_region}" --profile "${var.aws_profile}" --kubeconfig "${path.module}/generated/kubeconfig-apply"
      export KUBECONFIG="${path.module}/generated/kubeconfig-apply"
      kubectl apply -f "${local_file.karpenter_ec2nodeclass.filename}"
      kubectl apply -f "${local_file.karpenter_nodepool_llm.filename}"
      kubectl apply -f "${local_file.karpenter_nodepool.filename}"
    EOT
  }

  depends_on = [
    helm_release.karpenter,
    local_file.karpenter_ec2nodeclass,
    local_file.karpenter_nodepool,
  ]
}
