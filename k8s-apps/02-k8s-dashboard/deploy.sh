#!/usr/bin/env bash
# Deploys the official Kubernetes Dashboard.
#
# SECURITY NOTE: the admin ServiceAccount created below has cluster-admin --
# full control of the entire cluster, every namespace. That's what makes the
# Dashboard actually useful for a trainer walking through the whole cluster,
# but it also means this must NOT be exposed on a public LoadBalancer/NodePort
# the way the demo app and Grafana are -- a leaked token would mean full
# cluster takeover from the internet. Left as ClusterIP; access it via
# `kubectl proxy` or `kubectl port-forward` (see access.sh), from any machine
# that already has cluster-admin kubectl access (your laptop, the bastion).
#
# Usage: KUBECONFIG=<path> bash deploy.sh
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"

NAMESPACE="kubernetes-dashboard"

# kubernetes.github.io/dashboard/ (the documented Helm repo index) is
# currently returning 404 -- a hosting issue on their end, not the chart
# itself. Installing straight from the GitHub release tarball instead,
# which works identically and sidesteps that outage.
DASHBOARD_VERSION="7.14.0"
CHART_URL="https://github.com/kubernetes/dashboard/releases/download/kubernetes-dashboard-${DASHBOARD_VERSION}/kubernetes-dashboard-${DASHBOARD_VERSION}.tgz"

echo "==> Installing/upgrading the Dashboard (namespace: $NAMESPACE, ClusterIP only)"
helm upgrade --install kubernetes-dashboard "$CHART_URL" \
  --namespace "$NAMESPACE" --create-namespace \
  --set app.ingress.enabled=false \
  --wait --timeout 5m

echo "==> Creating a cluster-admin ServiceAccount for trainer login"
kubectl apply -n "$NAMESPACE" -f admin-user.yaml

echo ""
echo "-------------------------------------------------------------"
echo "Dashboard deployed. It is NOT publicly exposed (ClusterIP only)."
echo "Run ./access.sh to port-forward it and get a login token."
echo "-------------------------------------------------------------"
