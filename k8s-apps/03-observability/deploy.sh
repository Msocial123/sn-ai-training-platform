#!/usr/bin/env bash
# Deploys the log observability pipeline:
#   OTel Collector (DaemonSet, tails every pod's logs) --> Loki (storage)
#   --> Grafana (already running in 'monitoring', wired up via ConfigMaps)
#
# Usage: KUBECONFIG=<path> bash deploy.sh
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"

NAMESPACE="observability"

echo "==> Creating namespace '$NAMESPACE'"
kubectl create namespace "$NAMESPACE" --dry-run=client -o yaml | kubectl apply -f -

echo "==> Adding Helm repos"
helm repo add grafana https://grafana.github.io/helm-charts >/dev/null
helm repo add open-telemetry https://open-telemetry.github.io/opentelemetry-helm-charts >/dev/null
helm repo update grafana open-telemetry >/dev/null

echo "==> Installing Loki (single-binary, filesystem storage, 3-day retention)"
helm upgrade --install loki grafana/loki \
  --namespace "$NAMESPACE" \
  -f values-loki.yaml \
  --wait --timeout 5m

echo "==> Installing OTel Collector (DaemonSet, ships pod logs -> Loki)"
helm upgrade --install otel-collector open-telemetry/opentelemetry-collector \
  --namespace "$NAMESPACE" \
  -f values-otel-collector.yaml \
  --wait --timeout 5m

echo "==> Wiring Loki into the existing shared Grafana (datasource + dashboard)"
kubectl apply -f grafana-datasource-loki.yaml
kubectl apply -f grafana-dashboard-logs.yaml

echo ""
echo "-------------------------------------------------------------"
echo "Observability stack deployed."
echo "  - Loki:           $NAMESPACE/loki (3-day log retention)"
echo "  - OTel Collector: $NAMESPACE/otel-collector (DaemonSet)"
echo "  - Grafana:        already public (see 'terraform output grafana_url_hint')"
echo "    -> Dashboards -> 'Cluster Logs (Loki)'"
echo "Grafana's sidecar picks up the new datasource/dashboard within ~1 min,"
echo "no Grafana restart needed."
echo "-------------------------------------------------------------"
