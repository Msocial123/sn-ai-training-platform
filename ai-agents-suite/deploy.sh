#!/usr/bin/env bash
# Deploys the whole AI Agent Suite: 6 backend microservices + 1 frontend.
#
# No Docker/image registry needed -- each pod runs a stock python:3.12-slim
# or nginx:1.27-alpine image with the actual source code mounted in from a
# ConfigMap (recreated from these files every run), so redeploying after
# editing any app.py/HTML/CSS/JS is just: re-run this script.
#
# Usage:
#   export KUBECONFIG=/path/to/admin/kubeconfig
#   bash deploy.sh
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"

: "${KUBECONFIG:?Set KUBECONFIG to a cluster-admin kubeconfig first}"
NS="ai-agents"

echo "==> Namespace"
kubectl apply -f k8s/namespace.yaml

echo "==> Infra Monitor RBAC (ServiceAccount + scoped Roles -- see k8s/infra-monitor-rbac.yaml for the participant-namespace exclusion)"
kubectl apply -f k8s/infra-monitor-rbac.yaml

echo "==> Shared library + sample data ConfigMaps"
kubectl create configmap ai-agents-shared-lib -n "$NS" \
  --from-file=shared/servicenow_client.py --from-file=shared/llm_client.py --from-file=shared/bedrock_client.py --from-file=shared/ollama_client.py \
  --dry-run=client -o yaml | kubectl apply -f -

kubectl create configmap ai-agents-sample-data -n "$NS" \
  --from-file=data/sample_tickets.json --from-file=data/event_log.json \
  --dry-run=client -o yaml | kubectl apply -f -

echo "==> Per-service source ConfigMaps"
for svc in now-assist-agent knowledge-article-agent predictive-intelligence-agent password-reset-agent virtual-agent-demo process-mining-agent incident-watcher infra-monitor; do
  kubectl create configmap "${svc}-src" -n "$NS" \
    --from-file="services/${svc}/app.py" --from-file="services/${svc}/requirements.txt" \
    --dry-run=client -o yaml | kubectl apply -f -
done

echo "==> Frontend ConfigMaps"
kubectl create configmap ai-agents-frontend-src -n "$NS" \
  --from-file=frontend/index.html --from-file=frontend/style.css --from-file=frontend/app.js \
  --dry-run=client -o yaml | kubectl apply -f -
kubectl create configmap ai-agents-frontend-nginx-conf -n "$NS" \
  --from-file=frontend/nginx.conf \
  --dry-run=client -o yaml | kubectl apply -f -

echo "==> Deployments + Services"
kubectl apply -f k8s/services/
kubectl apply -f k8s/frontend.yaml
kubectl apply -f k8s/ollama/

echo "==> Restarting all deployments so pods pick up the latest ConfigMap content"
kubectl rollout restart deployment -n "$NS"

echo "==> Waiting for rollout (up to 3 min)..."
kubectl wait --for=condition=Available --timeout=180s -n "$NS" deployment --all

echo ""
echo "==> Waiting for the frontend's public hostname..."
for i in $(seq 1 30); do
  HOST=$(kubectl get svc ai-agents-frontend -n "$NS" -o jsonpath='{.status.loadBalancer.ingress[0].hostname}' 2>/dev/null || true)
  if [ -n "$HOST" ]; then
    echo ""
    echo "-------------------------------------------------------------"
    echo "AI Agent Suite is live at:  http://$HOST"
    echo "-------------------------------------------------------------"
    exit 0
  fi
  sleep 10
done
echo "Still waiting on the LoadBalancer hostname -- check later with:"
echo "  kubectl get svc ai-agents-frontend -n $NS"
