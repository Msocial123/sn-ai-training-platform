# Authentication: this Terraform project never reads or stores AWS keys
# itself. It authenticates via the named CLI profile below, which you
# configure once, outside this project:
#
#   aws configure --profile sn-training
#
# See README.md.
provider "aws" {
  region  = var.aws_region
  profile = var.aws_profile

  default_tags {
    tags = var.tags
  }
}

# The Kubernetes/Helm providers talk to the EKS cluster this same config
# creates. They authenticate the same way `kubectl`/`aws eks get-token`
# would -- via the AWS CLI exec plugin -- so tokens are always fresh,
# never stored in state.
provider "kubernetes" {
  host                   = module.eks.cluster_endpoint
  cluster_ca_certificate = base64decode(module.eks.cluster_certificate_authority_data)

  exec {
    api_version = "client.authentication.k8s.io/v1beta1"
    command     = "aws"
    args = [
      "eks", "get-token",
      "--cluster-name", module.eks.cluster_name,
      "--region", var.aws_region,
      "--profile", var.aws_profile,
    ]
  }
}

provider "helm" {
  kubernetes {
    host                   = module.eks.cluster_endpoint
    cluster_ca_certificate = base64decode(module.eks.cluster_certificate_authority_data)

    exec {
      api_version = "client.authentication.k8s.io/v1beta1"
      command     = "aws"
      args = [
        "eks", "get-token",
        "--cluster-name", module.eks.cluster_name,
        "--region", var.aws_region,
        "--profile", var.aws_profile,
      ]
    }
  }
}
