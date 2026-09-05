# ServiceNow AI Training — Multi-Tenant EKS Infrastructure

Terraform stand-up for the hands-on labs in the 8-hour ServiceNow AI Training
agenda: one shared, autoscaling EKS cluster, one isolated namespace per
participant (`participant-01` … `participant-35`), one shared cluster-wide
Grafana/Prometheus stack, and a bastion host for kubectl/SSH access.

**Status: live and verified in AWS account `165742853391` (`eu-west-2`).**

## What this creates (region: `eu-west-2`)

| Layer | Resource |
|---|---|
| Network | 1 VPC, 2 AZs, public+private subnets, 1 NAT gateway |
| Cluster | EKS `sn-ai-training-eks`, k8s 1.31, **public** API endpoint (0.0.0.0/0) |
| System nodes | Small fixed managed node group, `t3.medium`, min 1 / max 3 — runs core add-ons + monitoring only |
| Participant nodes | **Karpenter**-provisioned, `t3.medium`/`t3.large`, scales **0 → ~30-node-equivalent** based on actual pod demand |
| Access | Bastion EC2 host (public subnet, Elastic IP, SSH key auto-generated) |
| Isolation | 35× namespace, each with its own Role, RoleBinding, ServiceAccount, ResourceQuota, LimitRange, kubeconfig |
| Monitoring | One `kube-prometheus-stack` (Prometheus + Grafana + Alertmanager) for the whole cluster, pinned to the system nodes |

## Autoscaling architecture

Two separate node layers, on purpose:

- **System node group** (`eks.tf`) — a small, always-on managed node group
  (min 1, max 3) that hosts CoreDNS, kube-proxy, the Karpenter controller
  itself, and the monitoring stack. This is the cluster's real floor — it
  never scales to zero.
- **Karpenter** (`karpenter.tf`) — provisions and terminates EC2 nodes
  directly (no static ASG) for participant workloads only, based on actual
  unschedulable-pod pressure. Its `NodePool` (`participants`) is capped via
  a CPU/memory `limits` block approximating **30 nodes**
  (`node_max_size * 2` vCPU / `node_max_size * 4` GiB — see
  `variables.tf`), and can scale down to **0** participant nodes when idle
  (`consolidationPolicy: WhenEmptyOrUnderutilized`, 5 min delay).

**Verified live**: a test pod requesting 1.5 vCPU in `participant-07` (more
than the system node had spare) caused Karpenter to provision a new
`t3.medium` labeled `role=participant-workload` in ~2 minutes; after
deleting the workload, Karpenter terminated that node again automatically,
leaving just the 1-node system floor.

## Isolation model (the "break things and learn" boundary)

Each participant gets a namespace + a ServiceAccount whose Role can do
**anything inside that namespace** (deploy, scale, crash, delete, exec, port
forward) and **nothing outside it** — no other participant's namespace, no
cluster-scoped resources. **Verified live**: `participant-07`'s kubeconfig
gets `Forbidden` on both `-n participant-08` and `get nodes` (cluster-scoped).
A `ResourceQuota` (4 CPU / 8Gi mem / 20 pods) and a `LimitRange` (default
container requests/limits: 500m/512Mi, matched by default requests
100m/128Mi) stop one participant from starving the shared cluster — and stop
a pod with no explicit limits from silently exceeding them. **Participants
must set explicit `resources.limits` on anything beyond the LimitRange
default**, or the pod is rejected at admission (this is intentional, not a
bug — worth mentioning in Session 9's lab instructions).

The Grafana/Prometheus stack is shared read-only visibility, not something
any participant can break for anyone else.

## Prerequisites

- Terraform ≥ 1.5, AWS CLI v2, kubectl, Helm — all confirmed installed locally.
- An AWS account with permissions to create VPC/EKS/EC2/IAM resources (verified: account `165742853391`, user `Murali`).

## 1. Configure AWS credentials (one-time, outside this project)

Your access key is **not** stored anywhere in this Terraform project. It's
in a named CLI profile instead:

```bash
aws configure --profile sn-training
```

(Already done in this session — profile `sn-training` is ready to use.)

**Still recommended:** rotate this key in the IAM console at some point,
since it passed through a chat/download flow before this setup.

## 2. Review `terraform.tfvars`

Every tunable value (region, node sizes, min/max, participant count, quotas,
CIDRs) lives in [`terraform.tfvars`](terraform.tfvars). Notable defaults,
since you asked to keep it simple/public:

- `eks_public_access_cidrs = ["0.0.0.0/0"]` — EKS API open to the internet.
- `allowed_ssh_cidrs = ["0.0.0.0/0"]` — bastion SSH open to the internet.
  Both work fine with valid credentials required for anything to actually
  happen, but if you want to tighten either later, it's a one-line edit +
  `terraform apply`.

## 3. Init, plan, apply

```bash
cd terraform
terraform init
terraform plan -out=tfplan
terraform apply tfplan
```

First apply takes **~15–20 minutes** (EKS control plane provisioning is the
slow part). If it errors on the very first run with something like "cluster
doesn't exist yet" for a Kubernetes/Helm resource, that's the well-known EKS
chicken-and-egg case — just run `terraform apply` again.

## 4. What you get back

```bash
terraform output configure_kubectl        # sets up your own cluster-admin kubectl
terraform output bastion_ssh_command      # ssh onto the bastion
terraform output participant_namespaces   # list of all 35 namespaces
terraform output participant_kubeconfig_dir
terraform output check_karpenter_nodes
terraform output grafana_url_hint
terraform output -raw grafana_admin_password
```

Participant kubeconfigs are written to `kubeconfigs/participant-XX.yaml` —
each only works inside its own namespace, no AWS credentials needed. You can
hand a file out directly:

```bash
kubectl --kubeconfig kubeconfigs/participant-07.yaml get pods
kubectl --kubeconfig kubeconfigs/participant-07.yaml -n participant-08 get pods   # denied, by design
```

...but for 35 people on their own laptops, it's easier to hand out a
self-contained kit per person instead (see below).

## 5. Distributing access to all 35 participants

Every participant connects **from their own machine**, straight to the
public EKS endpoint — no bastion, no AWS account, no AWS credentials. Their
`participant-XX.yaml` kubeconfig carries a Kubernetes ServiceAccount token
scoped to only their own namespace; that's the only thing their machine
needs.

Build one ready-to-send zip per participant:

```bash
python scripts/package_participant_kits.py
```

This produces `dist/participant-01.zip` … `dist/participant-35.zip`. Each
zip is self-contained and **only** grants access to that one participant's
namespace — safe to email or hand out individually. Each contains:

- `participant-XX.yaml` — their kubeconfig
- `connect.sh` — for macOS / Linux / WSL / Git Bash
- `connect.ps1` — for Windows PowerShell
- `README.txt` — plain-language instructions for them

A participant just needs `kubectl` installed, then from the unzipped
folder:

```bash
# macOS / Linux / WSL
./connect.sh

# Windows PowerShell
.\connect.ps1
```

The script finds their kubeconfig automatically, points `kubectl` at it,
and runs a live connection test — confirming both that they're in and that
they're correctly denied any other namespace. **Verified end-to-end**
against the live cluster from a separate machine/directory.

## Bastion host — a note on `sudo su`

The bastion configures `kubectl` for **both** `ec2-user` and `root` at boot
(root needs its own kubeconfig — `sudo su` loads root's own home directory,
so ec2-user's `~/.kube/config` isn't visible to it). If you ever see
`kubectl` on the bastion fail with `connect: connection refused` to
`localhost:8080`, it means whichever user you're running as has no
kubeconfig — re-run `aws eks update-kubeconfig --name sn-ai-training-eks
--region eu-west-2` as that user.

A related, subtler issue this project accounts for: because the cluster has
both public *and* private endpoint access on, any client **inside the VPC**
(the bastion included) resolves the API hostname to its private IP, not the
public one — so the bastion's security group needs an explicit allow into
the cluster's control-plane security group on 443 (`cluster_security_group_
additional_rules` in `eks.tf`), or it times out instead of connecting.
Already wired up and verified working.

## Files

- `versions.tf` / `providers.tf` — provider setup, AWS profile auth.
- `variables.tf` / `terraform.tfvars` — every tunable value.
- `vpc.tf` — networking.
- `eks.tf` — cluster, system node group, IRSA roles (EBS CSI + Karpenter), bastion-to-cluster SG rule.
- `karpenter.tf` — Karpenter controller, EC2NodeClass, NodePool (drives 0↔30-equivalent scaling).
- `bastion.tf` — SSH key generation, bastion EC2 + Elastic IP, IAM, EKS access entry, kubectl/helm/kubeconfig bootstrap.
- `namespaces.tf` — the 35 participant namespaces + RBAC + quotas + kubeconfigs.
- `monitoring.tf` — shared kube-prometheus-stack, pinned to system nodes.
- `outputs.tf` — everything you need after `apply`.
- `participant-kit/` — the generic connect.sh / connect.ps1 / README.txt template handed to every participant.
- `scripts/package_participant_kits.py` — builds `dist/participant-XX.zip` for all 35 participants.

## Cost note

This is real, billed AWS infrastructure. Rough on-demand estimate for
`eu-west-2` at steady state (system node only, no participant nodes running):
EKS control plane (~$0.10/hr) + 1× `t3.medium` (~$0.04/hr) + 1 NAT gateway
(~$0.05/hr + data) + 1 `t3.micro` bastion (~$0.01/hr) + 1 Grafana
LoadBalancer (~$0.025/hr) ≈ **$0.22/hr** idle. Each participant node
Karpenter adds during a busy lab session is another `t3.medium`
(~$0.04/hr) or `t3.large` (~$0.08/hr) — at the theoretical full 30-node
ceiling, roughly **+$1.2–2.4/hr** on top. In practice it scales with real
demand and back down to 0 within ~5 minutes of going idle. **Tear it all
down when the training day is over:**

```bash
terraform destroy
```

