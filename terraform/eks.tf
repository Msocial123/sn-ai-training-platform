module "eks" {
  source  = "terraform-aws-modules/eks/aws"
  version = "~> 20.31"

  cluster_name    = var.cluster_name
  cluster_version = var.kubernetes_version

  vpc_id     = module.vpc.vpc_id
  subnet_ids = module.vpc.private_subnets

  # --- "Make the cluster public" ---
  # Public access so kubectl works from anywhere (your laptop, the bastion,
  # CI) with zero VPN/tunnel setup. Private access is also left on so nodes
  # inside the VPC talk to the control plane over the private ENI instead of
  # routing out through the NAT gateway -- cheaper and more reliable, with
  # no extra steps for you.
  cluster_endpoint_public_access       = true
  cluster_endpoint_public_access_cidrs = var.eks_public_access_cidrs
  cluster_endpoint_private_access      = true

  # Because private access is on, any client INSIDE the VPC (the bastion
  # included) resolves the cluster endpoint hostname to its private IP via
  # the Route53 zone EKS associates with the VPC -- that's true regardless
  # of which subnet the client sits in. So the bastion needs an explicit
  # allow from its own security group to reach the control plane ENIs on
  # 443, or it silently times out instead of using the public path.
  cluster_security_group_additional_rules = {
    ingress_bastion_https = {
      description              = "Bastion to EKS API (private endpoint path)"
      protocol                 = "tcp"
      from_port                = 443
      to_port                  = 443
      type                     = "ingress"
      source_security_group_id = aws_security_group.bastion.id
    }
  }

  # Modern EKS Access Entries (no more hand-editing the aws-auth ConfigMap).
  # The IAM identity that runs `terraform apply` (your AKIASNFY... key)
  # automatically gets cluster-admin.
  authentication_mode                      = "API"
  enable_cluster_creator_admin_permissions = true

  cluster_addons = {
    coredns = {
      most_recent = true
    }
    kube-proxy = {
      most_recent = true
    }
    vpc-cni = {
      most_recent = true
    }
    aws-ebs-csi-driver = {
      most_recent              = true
      service_account_role_arn = module.ebs_csi_irsa.iam_role_arn
    }
  }

  enable_irsa = true

  # A small, fixed-size managed node group for cluster system components only
  # (CoreDNS, kube-proxy, the Karpenter controller itself, the shared
  # monitoring stack). Participant workload nodes are NOT here -- Karpenter
  # provisions those dynamically, see karpenter.tf.
  eks_managed_node_groups = {
    system = {
      name           = "system-workers"
      instance_types = var.node_instance_types
      capacity_type  = "ON_DEMAND"

      min_size     = var.system_node_min_size
      max_size     = var.system_node_max_size
      desired_size = var.system_node_desired_size

      subnet_ids = module.vpc.private_subnets

      labels = {
        role = "system"
      }

      tags = var.tags
    }
  }

  node_security_group_tags = merge(var.tags, {
    "karpenter.sh/discovery" = var.cluster_name
  })

  tags = var.tags
}

# IRSA role for the EBS CSI driver (needed for Prometheus/Grafana persistent
# volumes and anything participants provision with a PVC).
module "ebs_csi_irsa" {
  source  = "terraform-aws-modules/iam/aws//modules/iam-role-for-service-accounts-eks"
  version = "~> 5.48"

  role_name             = "${var.project_name}-ebs-csi-irsa"
  attach_ebs_csi_policy = true

  oidc_providers = {
    main = {
      provider_arn               = module.eks.oidc_provider_arn
      namespace_service_accounts = ["kube-system:ebs-csi-controller-sa"]
    }
  }

  tags = var.tags
}

# Karpenter: provisions and terminates EC2 nodes directly (no static ASG)
# based on actual unschedulable-pod pressure from participant workloads.
# This module creates the controller IRSA role, the IAM role + instance
# profile EC2 instances Karpenter launches will run under, and the SQS
# queue + EventBridge rules for spot/rebalance interruption handling.
module "karpenter" {
  source  = "terraform-aws-modules/eks/aws//modules/karpenter"
  version = "~> 20.31"

  cluster_name = module.eks.cluster_name

  enable_v1_permissions = true # we deploy the Karpenter v1.x Helm chart

  enable_irsa            = true
  irsa_oidc_provider_arn = module.eks.oidc_provider_arn
  # irsa_namespace_service_accounts defaults to ["karpenter:karpenter"],
  # matching the "karpenter" namespace + service account name used below.

  node_iam_role_additional_policies = {
    AmazonSSMManagedInstanceCore = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
  }

  tags = var.tags
}
