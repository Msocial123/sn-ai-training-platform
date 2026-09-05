#!/usr/bin/env bash
# Deploys the "Online Boutique" microservices demo
# (https://github.com/devopswithcloud/microservices-demo) into its own
# "trainer" namespace -- separate from the 35 participant namespaces, for
# the trainer to showcase live during the session.
#
# Usage: KUBECONFIG=<path> bash deploy.sh
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"

NAMESPACE="trainer"

echo "==> Creating namespace '$NAMESPACE' (if it doesn't already exist)"
kubectl create namespace "$NAMESPACE" --dry-run=client -o yaml | kubectl apply -f -

echo "==> Deploying the 11 Online Boutique microservices into '$NAMESPACE'"
kubectl apply -n "$NAMESPACE" -f kubernetes-manifests.yaml

echo "==> Waiting for all deployments to become available (up to 5 min)..."
kubectl wait --for=condition=Available --timeout=300s -n "$NAMESPACE" deployment --all

echo "==> App is exposed via the built-in 'frontend-external' LoadBalancer Service."
echo "    Waiting for AWS to assign a public hostname (can take ~1-2 min)..."
for i in $(seq 1 30); do
  HOST=$(kubectl get svc frontend-external -n "$NAMESPACE" -o jsonpath='{.status.loadBalancer.ingress[0].hostname}' 2>/dev/null || true)
  if [ -n "$HOST" ]; then
    echo ""
    echo "-------------------------------------------------------------"
    echo "Online Boutique is live at:  http://$HOST"
    echo "-------------------------------------------------------------"
    exit 0
  fi
  sleep 10
done

echo "Still waiting on the LoadBalancer hostname -- check later with:"
echo "  kubectl get svc frontend-external -n $NAMESPACE"
