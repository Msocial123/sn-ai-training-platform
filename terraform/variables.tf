############################################
# Core / AWS
############################################

variable "aws_region" {
  description = "AWS region to deploy into."
  type        = string
  default     = "eu-west-2"
}

variable "aws_profile" {
  description = "Named AWS CLI profile Terraform authenticates with. Credentials are NEVER stored in this project — configure the profile once with `aws configure --profile <this value>`."
  type        = string
  default     = "sn-training"
}

variable "project_name" {
  description = "Short name used to prefix/tag every resource."
  type        = string
  default     = "sn-ai-training"
}

variable "tags" {
  description = "Common tags applied to all resources."
  type        = map(string)
  default = {
    Project     = "ServiceNow-AI-Training"
    ManagedBy   = "Terraform"
    Environment = "training"
  }
}

############################################
# Networking
############################################

variable "vpc_cidr" {
  description = "CIDR block for the VPC."
  type        = string
  default     = "10.60.0.0/16"
}

variable "azs" {
  description = "Availability zones to spread subnets across."
  type        = list(string)
  default     = ["eu-west-2a", "eu-west-2b"]
}

variable "single_nat_gateway" {
  description = "Use one NAT gateway for all private subnets (cheaper, simpler) instead of one per AZ (more resilient, costs more)."
  type        = bool
  default     = true
}

############################################
# EKS cluster
############################################

variable "cluster_name" {
  description = "EKS cluster name."
  type        = string
  default     = "sn-ai-training-eks"
}

variable "kubernetes_version" {
  description = "EKS Kubernetes version."
  type        = string
  default     = "1.31"
}

variable "eks_public_access_cidrs" {
  description = "CIDRs allowed to reach the public EKS API endpoint. Set to 0.0.0.0/0 for fully open access (simplest, matches 'make it public'), or restrict to your IP(s) for a bit more safety with the same amount of setup."
  type        = list(string)
  default     = ["0.0.0.0/0"]
}

############################################
# Worker nodes
############################################

variable "node_instance_types" {
  description = "EC2 instance type(s) for the small, fixed SYSTEM node group (core add-ons + monitoring)."
  type        = list(string)
  default     = ["t3.medium"]
}

variable "system_node_min_size" {
  description = "Minimum nodes in the system node group -- this is the cluster's permanent floor (satisfies 'minimum 1')."
  type        = number
  default     = 1
}

variable "system_node_max_size" {
  description = "Maximum nodes in the system node group. Kept small -- this group only runs cluster add-ons and monitoring, not participant workloads."
  type        = number
  default     = 3
}

variable "system_node_desired_size" {
  description = "Initial desired node count for the system node group."
  type        = number
  default     = 1
}

# ---- Karpenter-driven participant workload nodes ----
# Karpenter provisions/removes these nodes directly (no static ASG size).
# node_min_size / node_max_size describe the overall floor/ceiling for this
# fleet: 1 (can scale toward zero, but the system group's floor of 1 already
# covers the cluster minimum) up to 30, expressed as a resource ceiling
# (see karpenter.tf) rather than a literal instance-count field, because
# that's how Karpenter's NodePool API works.

variable "karpenter_node_instance_types" {
  description = "Instance types Karpenter is allowed to choose from for participant workload nodes -- giving it a few options (not just one) is what lets it bin-pack efficiently."
  type        = list(string)
  default     = ["t3.medium", "t3.large"]
}

variable "node_min_size" {
  description = "Conceptual floor for participant workload nodes. Karpenter can scale this fleet toward 0 when idle; the cluster's real floor of 1 running node is guaranteed by the system node group instead."
  type        = number
  default     = 1
}

variable "node_max_size" {
  description = "Ceiling for participant workload nodes, expressed as a node count -- translated into a Karpenter NodePool CPU/memory limit (node_max_size * per-node vCPU/mem) in karpenter.tf."
  type        = number
  default     = 30
}

variable "node_capacity_type" {
  description = "ON_DEMAND or SPOT for Karpenter-provisioned participant nodes. SPOT is materially cheaper for a training cluster that scales up/down all day, at the cost of possible node interruption (Karpenter handles the interruption/drain automatically)."
  type        = string
  default     = "ON_DEMAND"
}

############################################
# Bastion host
############################################

variable "bastion_instance_type" {
  description = "EC2 instance type for the bastion host."
  type        = string
  default     = "t3.micro"
}

variable "allowed_ssh_cidrs" {
  description = "CIDRs allowed to SSH into the bastion on port 22. Defaults fully open to match the 'keep it simple / public' instruction -- tighten this to your IP(s) in terraform.tfvars when you get a chance."
  type        = list(string)
  default     = ["0.0.0.0/0"]
}

############################################
# Participants / multi-tenant namespaces
############################################

variable "participant_count" {
  description = "Number of participants to provision isolated namespaces for."
  type        = number
  default     = 35
}

variable "participant_namespace_prefix" {
  description = "Namespace name prefix; namespaces are <prefix>-01 .. <prefix>-NN."
  type        = string
  default     = "participant"
}

variable "participant_cpu_quota" {
  description = "Total CPU (requests+limits, in millicores as a string e.g. '4') a single participant namespace may consume. Keeps one participant from starving the shared cluster."
  type        = string
  default     = "4"
}

variable "participant_memory_quota" {
  description = "Total memory a single participant namespace may consume, e.g. '8Gi'."
  type        = string
  default     = "8Gi"
}

variable "participant_pod_quota" {
  description = "Max number of pods a single participant namespace may run at once."
  type        = number
  default     = 20
}

############################################
# Monitoring (single, cluster-wide)
############################################

variable "enable_monitoring" {
  description = "Deploy the shared kube-prometheus-stack (Prometheus + Grafana + Alertmanager) once for the whole cluster."
  type        = bool
  default     = true
}

variable "grafana_service_type" {
  description = "Kubernetes Service type for Grafana. LoadBalancer gives everyone a public URL with zero extra setup (matches 'keep it simple / public')."
  type        = string
  default     = "LoadBalancer"
}
