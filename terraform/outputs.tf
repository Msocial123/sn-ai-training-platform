output "cluster_name" {
  value = module.eks.cluster_name
}

output "cluster_endpoint" {
  value = module.eks.cluster_endpoint
}

output "region" {
  value = var.aws_region
}

output "configure_kubectl" {
  description = "Run this locally (with the sn-training AWS profile) to get cluster-admin kubectl access."
  value       = "aws eks update-kubeconfig --name ${module.eks.cluster_name} --region ${var.aws_region} --profile ${var.aws_profile}"
}

output "bastion_public_ip" {
  value = aws_eip.bastion.public_ip
}

output "bastion_ssh_command" {
  value = "ssh -i keys/${var.project_name}-bastion-key.pem ec2-user@${aws_eip.bastion.public_ip}"
}

output "participant_namespaces" {
  value = [for k, v in local.participants : v]
}

output "participant_kubeconfig_dir" {
  description = "Each file here is a ready-to-use, namespace-scoped kubeconfig -- hand out one per participant."
  value       = "${path.module}/kubeconfigs/"
}

output "grafana_admin_password" {
  value     = random_password.grafana_admin.result
  sensitive = true
}

output "grafana_url_hint" {
  description = "Grafana is a LoadBalancer Service -- once it's provisioned, find the URL with the kubectl command below."
  value       = "kubectl -n monitoring get svc kube-prometheus-stack-grafana -o jsonpath='{.status.loadBalancer.ingress[0].hostname}'"
}

output "karpenter_node_role" {
  description = "IAM role Karpenter-provisioned participant nodes run under."
  value       = module.karpenter.node_iam_role_name
}

output "check_karpenter_nodes" {
  description = "See the nodes Karpenter has actually provisioned for participant workloads at any point in time."
  value       = "kubectl get nodes -l role=participant-workload"
}
