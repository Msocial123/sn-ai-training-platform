#!/usr/bin/env bash
# Deploys everything in this folder, in order:
#   1. trainer namespace + Online Boutique demo app (exposed via public LB)
#   2. Kubernetes Dashboard (cluster-admin, kept ClusterIP-only -- see 02-k8s-dashboard/deploy.sh)
#   3. Loki + OTel Collector + Grafana wiring (logs pipeline)
#
# Usage:
#   export KUBECONFIG=/path/to/your/kubeconfig    # needs cluster-admin
#   bash deploy-all.sh
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"

: "${KUBECONFIG:?Set KUBECONFIG to a cluster-admin kubeconfig first (e.g. terraform/generated/kubeconfig-apply, or run: aws eks update-kubeconfig --name sn-ai-training-eks --region eu-west-2)}"

echo "############################################################"
echo "# 1/3  Trainer app (Online Boutique)"
echo "############################################################"
bash 01-trainer-app/deploy.sh

echo ""
echo "############################################################"
echo "# 2/3  Kubernetes Dashboard"
echo "############################################################"
bash 02-k8s-dashboard/deploy.sh

echo ""
echo "############################################################"
echo "# 3/3  Observability (Loki + OTel Collector + Grafana)"
echo "############################################################"
bash 03-observability/deploy.sh

echo ""
echo "All done. See README.md for access instructions."
