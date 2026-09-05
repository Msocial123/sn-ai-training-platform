# Trainer App, K8s Dashboard & Observability Stack

Scripted deployment of everything the trainer showcases live during the
ServiceNow AI Training sessions, on top of the shared EKS cluster
(`sn-ai-training-eks`, see [../terraform](../terraform)).

**Status: live and verified.**

## What's deployed

| Piece | Where | How to reach it |
|---|---|---|
| Online Boutique demo app (11 microservices) | `trainer` namespace | Public LoadBalancer — see `terraform output` below or `kubectl get svc frontend-external -n trainer` |
| Kubernetes Dashboard | `kubernetes-dashboard` namespace | ClusterIP only, deliberately **not public** — port-forward via `02-k8s-dashboard/access.sh` |
| Loki (log storage) | `observability` namespace | Internal only (`loki.observability.svc.cluster.local:3100`) |
| OTel Collector (DaemonSet, ships pod logs → Loki) | `observability` namespace | Internal only |
| "Cluster Logs (Loki)" dashboard | Grafana (already public, `monitoring` namespace) | Grafana → Dashboards → **Cluster Logs (Loki)** |

## Run it yourself

```bash
export KUBECONFIG=../terraform/generated/kubeconfig-apply   # or your own admin kubeconfig
bash deploy-all.sh
```

Or run each piece independently (they don't depend on each other):
`01-trainer-app/deploy.sh`, `02-k8s-dashboard/deploy.sh`, `03-observability/deploy.sh`.

## Why the Dashboard isn't public

The Dashboard's login is a **cluster-admin** ServiceAccount token — full
control of the entire cluster, every namespace, every participant's work.
That's what makes it useful for a trainer to browse the whole cluster live,
but it's a materially bigger risk than anything else made public in this
project (the app frontend, Grafana): a leaked token means total cluster
takeover from the internet, not just a defaced demo page. It's deployed
ClusterIP-only; run `02-k8s-dashboard/access.sh` from anywhere with
cluster-admin kubectl access (your laptop, the bastion) to port-forward it
and get a fresh token. If you want it public anyway, that's a one-line
Helm value change — just say so.

## The observability pipeline, and what it actually does

```
pod logs (every node) --> OTel Collector (DaemonSet, filelog receiver)
                        --> enriched with k8s.namespace.name / pod / container
                        --> shipped via OTLP to Loki's native /otlp endpoint
                        --> queried by Grafana (Loki datasource, uid "loki")
```

Grafana already had sidecars watching for labeled ConfigMaps
(`grafana_datasource: "1"`, `grafana_dashboard: "1"`) — no Helm re-release
needed, just `kubectl apply` the two ConfigMaps in `03-observability/`.

**Verified live**: queried Loki directly and confirmed real log streams
labeled `k8s_namespace_name` for `kube-system`, `kubernetes-dashboard`,
`observability`, and `trainer` (the demo app) — the pipeline is genuinely
carrying logs, not just deployed-and-hoped.

**Known gap**: the system node group is small (min 1, max 3) and already
hosts a lot of cluster add-ons; it's hit AWS's per-node pod ceiling for
`t3.medium`, so the log collector can't schedule a copy there. Effect:
`kube-system`/`monitoring`'s own logs on that one node aren't collected —
everything on the Karpenter-provisioned participant-workload nodes
(**including the trainer app**) is unaffected and fully collected. Not
fixed here to keep this pass scoped; bumping the system node's instance
type or enabling VPC CNI prefix delegation would close it if it matters to
you later.

## Real bugs hit and fixed along the way (for anyone re-running this)

1. **No default StorageClass** — the cluster only had the legacy in-tree
   `gp2` class, which doesn't work on modern EKS nodes. Any PVC (Loki
   included) would sit `Pending` forever. Fixed with a proper `gp3`
   StorageClass wired to the already-installed EBS CSI driver — see
   [`../terraform/storage.tf`](../terraform/storage.tf) (infra-level fix,
   belongs in Terraform, not a one-off `kubectl` patch).
2. **Loki's default cache sizing** (`chunksCache`/`resultsCache`) wants
   ~8-10GB of memcached — bigger than any node in this cluster. Disabled
   both in `values-loki.yaml`; fine at this log volume.
3. **The `loki` OTel exporter is deprecated/removed** from the collector's
   contrib distribution — Loki now ingests OTLP natively. Fixed by using
   the standard `otlphttp` exporter against Loki's `/otlp` endpoint
   instead, and by adding `allow_structured_metadata: true` to Loki's
   config (required for OTLP ingestion). This also changes the label name
   from a plain `namespace` to `k8s_namespace_name` — already reflected in
   the dashboard JSON.
4. **kubernetes.github.io/dashboard's Helm repo index** was returning 404
   (a hosting issue on their end) — installed straight from the GitHub
   release tarball instead, same result.
