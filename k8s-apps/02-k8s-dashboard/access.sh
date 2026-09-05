#!/usr/bin/env bash
# Port-forwards the Dashboard to your machine and prints a fresh login token.
# Run this from anywhere with cluster-admin kubectl access (your laptop,
# or the bastion).
set -euo pipefail

NAMESPACE="kubernetes-dashboard"

echo "==> Login token (paste into the Dashboard's token field):"
kubectl -n "$NAMESPACE" create token admin-user --duration=8h
echo ""
echo "==> Starting port-forward on https://localhost:8443 (Ctrl+C to stop)"
echo "    Open: https://localhost:8443"
kubectl -n "$NAMESPACE" port-forward svc/kubernetes-dashboard-kong-proxy 8443:443
