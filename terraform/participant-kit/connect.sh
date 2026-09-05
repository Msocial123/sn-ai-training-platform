#!/usr/bin/env bash
# Run this from the same folder as your participant-XX.yaml kubeconfig file.
# macOS / Linux / WSL / Git Bash.
set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
KCFG="$(ls "$DIR"/participant-*.yaml 2>/dev/null | head -1 || true)"

if [ -z "$KCFG" ]; then
  echo "Could not find a participant-XX.yaml kubeconfig file next to this script."
  echo "Make sure connect.sh and your participant-XX.yaml are in the same folder."
  exit 1
fi

if ! command -v kubectl >/dev/null 2>&1; then
  echo "kubectl is not installed. Install it, then re-run this script:"
  echo ""
  echo "  macOS (Homebrew):  brew install kubectl"
  echo "  Linux:             curl -LO \"https://dl.k8s.io/release/\$(curl -L -s https://dl.k8s.io/release/stable.txt)/bin/linux/amd64/kubectl\" && chmod +x kubectl && sudo mv kubectl /usr/local/bin/"
  echo "  Docs:              https://kubernetes.io/docs/tasks/tools/"
  exit 1
fi

export KUBECONFIG="$KCFG"
NS=$(kubectl config view --minify -o jsonpath='{.contexts[0].context.namespace}' 2>/dev/null || echo "")

echo "Using kubeconfig: $KCFG"
echo "Your namespace:   $NS"
echo ""
echo "Testing access to the cluster..."
if kubectl get pods >/dev/null 2>&1; then
  echo "Connected. You have full access inside '$NS' only."
else
  echo "Could not reach the cluster. Check your internet connection and try again."
  echo "If this keeps failing, contact the trainer -- your token or the cluster's"
  echo "public access settings may need checking."
  exit 1
fi

echo ""
echo "-------------------------------------------------------------"
echo "You're connected as: $NS"
echo ""
echo "Try:"
echo "  kubectl get all -n $NS"
echo "  kubectl get pods -n participant-01     # <- try someone else's namespace, it will be denied"
echo ""
echo "To make this permanent for your current terminal session, run:"
echo "  export KUBECONFIG=\"$KCFG\""
echo "-------------------------------------------------------------"
