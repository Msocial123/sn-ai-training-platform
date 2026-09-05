# ServiceNow AI Agent Suite

A working microservice for each AI agent demonstrated in the training
(Sessions 3, 5, 6, 7, 8), plus one frontend tying them into a single
tabbed website. Deployed to the `ai-agents` namespace on the shared EKS
cluster.

## ⚠️ About the credentials shared in chat

Two ServiceNow logins (a personal SSO account and a `dev403046` admin
account, the latter with its password embedded directly in a URL) were
pasted in plaintext in the conversation that produced this project.
**Neither was used anywhere in this codebase.** Logging into ServiceNow
with a username/password on your behalf isn't something I do, regardless
of being asked to — full stop. **Reset both passwords** when you're back;
treat them as compromised the moment they left the ServiceNow login page.

Real integration should use ServiceNow's proper machine-to-machine auth
instead (OAuth 2.0 client credentials, or a scoped API service account) —
see [Connecting to real ServiceNow](#connecting-to-real-servicenow) below.

## Architecture

```
Browser
  └── ai-agents-frontend (nginx, public LoadBalancer)
        ├── /api/now-assist/*       → now-assist-agent
        ├── /api/knowledge/*        → knowledge-article-agent
        ├── /api/predictive/*       → predictive-intelligence-agent
        ├── /api/password-reset/*   → password-reset-agent
        ├── /api/virtual-agent/*    → virtual-agent-demo
        └── /api/process-mining/*   → process-mining-agent
                (each: FastAPI, ClusterIP-only, ai-agents namespace)
```

Every backend is a small FastAPI service in its own folder under
`services/`, each independently deployable, each reading:
- `shared/servicenow_client.py` — OAuth-based ServiceNow client (returns
  `None` until configured, so callers fall back to sample data)
- `shared/llm_client.py` — Claude API client (same fallback pattern)
- `data/sample_tickets.json` / `data/event_log.json` — realistic sample
  IT-support data (VPN issues, password resets, onboarding, etc. — the
  same domain used in the training syllabus itself)

**No Docker/registry needed to run this**: each pod is a stock
`python:3.12-slim` or `nginx:1.27-alpine` image with the actual source
code mounted in from a Kubernetes ConfigMap (rebuilt from these files on
every `deploy.sh` run) — so editing any `app.py`/HTML/CSS/JS and
re-running `deploy.sh` is the entire dev loop. `Dockerfile`s are included
in every service folder for when you want a real image-based pipeline
later (e.g. once container tooling is available, or via CI).

## Deploy / redeploy

```bash
export KUBECONFIG=../terraform/generated/kubeconfig-apply   # or your own admin kubeconfig
bash deploy.sh
```

Prints the public URL when done (also: `kubectl get svc ai-agents-frontend -n ai-agents`).

## What's real vs. what's a stand-in

| Agent | What's real today | What's a placeholder |
|---|---|---|
| Now Assist | Full working summarization + recommendation flow | Summaries are template-based until a real LLM call succeeds (see [Bedrock / Nova Pro](#bedrock--amazon-nova-pro-integration) below — currently blocked on model access, not code) |
| Knowledge Article | Duplicate detection (real text-similarity scoring) | Article drafting is template-based until an LLM key is set |
| Predictive Intelligence | Full classify/predict flow, transparent and deterministic | The classifier is keyword rules, not a trained model — there's no historical labeled ticket volume to train one on yet. Swap in a real model (e.g. scikit-learn over exported incident history) once that data exists — this is also literally called out in your own syllabus notes ("these agents need solid datasets") |
| Password Reset | Full workflow state machine, with a real approval branch for privileged usernames | Doesn't touch a real Active Directory / Integration Hub — there's nothing to connect to yet |
| Virtual Agent | Working chat flow (ticket status, reset trigger, escalation) | Keyword-matched intent, not trained NLU (a real ServiceNow Virtual Agent trains on your topic library) |
| Process Mining | Full bottleneck analysis over event-log data | The event log is synthetic (deliberately includes a slow "Assigned → In Progress" step so the demo has something to find) — swap in a real exported process-mining log when you have one |

None of this is faked to look more finished than it is — every "not real
yet" above is also visible live in the UI (the ServiceNow/LLM connection
badges in the header, and inline notes in each agent's output).

## Connecting to real ServiceNow

Set this up **once you're back and have reset the exposed passwords**:

1. In ServiceNow: **System OAuth → Application Registry → New → "Create
   an OAuth API endpoint for external clients"**. Note the Client ID and
   Client Secret it generates — these are scoped, revocable credentials,
   not your personal login.
2. Create the secret (never commit this, it's just a local command):
   ```bash
   kubectl create secret generic servicenow-oauth -n ai-agents \
     --from-literal=instance-url=https://YOUR_INSTANCE.service-now.com \
     --from-literal=client-id=YOUR_CLIENT_ID \
     --from-literal=client-secret=YOUR_CLIENT_SECRET
   kubectl rollout restart deployment -n ai-agents
   ```
3. That's it — `shared/servicenow_client.py` picks these up automatically
   and every agent starts reading/writing real ServiceNow data instead of
   the sample dataset.

## Bedrock / Amazon Nova Pro integration

`shared/bedrock_client.py` calls Nova Pro via a Bedrock API key (bearer
token over HTTPS — no boto3, no AWS credentials needed beyond the token
itself). It's the first provider `shared/llm_client.py` tries, ahead of
Anthropic. Wired into **Now Assist**, **Knowledge Article**, and
**Virtual Agent** (the three agents that generate free text).

```bash
kubectl create secret generic bedrock-credentials -n ai-agents \
  --from-literal=bearer-token=YOUR_BEDROCK_API_KEY \
  --from-literal=region=us-east-1 \
  --from-literal=model-id=amazon.nova-pro-v1:0
kubectl rollout restart deployment -n ai-agents
```

### Break-test results (`tests/break_test.sh`)

Ran the full resilience suite against the live deployment — concurrent
load, oversized/empty input, invalid IDs, and a genuine live Bedrock
failure (see below). **All 6 checks passed**: every request returned the
correct status code, no 500s, no crashes, even while every single Bedrock
call was failing underneath.

**Real finding, not a code bug**: Bedrock currently returns
`400 Operation not allowed` for every Nova Pro request on this account,
across every region and model-ID format tested (`amazon.nova-pro-v1:0`
and the cross-region inference-profile form `us.amazon.nova-pro-v1:0`,
in `us-east-1`, `us-east-2`, and `us-west-2`). That specific, consistent
error — not a routing or auth-token-format problem — points to **Nova Pro
not yet being enabled for this account** in the Bedrock console:
**Bedrock → Model access → Request/enable access for the Amazon Nova
family**. That's a one-time, account-admin, console-only action; nothing
code-side to fix. Once granted, no redeploy is needed for it to start
working — the pods already have everything wired up and will start
getting real completions on the very next request.

While blocked, every agent runs on the template fallback exactly as
designed — that's the resilience property being tested, and it held.

## Connecting Anthropic instead (or as a second option)

```bash
kubectl create secret generic llm-credentials -n ai-agents \
  --from-literal=api-key=YOUR_ANTHROPIC_API_KEY
kubectl rollout restart deployment -n ai-agents
```

Bedrock still takes priority if both secrets exist — delete
`bedrock-credentials` if you want Anthropic to be tried first.

## Files

- `data/` — shared sample datasets (tickets, process event log)
- `shared/` — the ServiceNow, Bedrock/Nova, and Anthropic client libraries every service imports
- `services/<agent-name>/` — one self-contained microservice per agent (`app.py`, `requirements.txt`, `Dockerfile`)
- `frontend/` — the tabbed website (static HTML/CSS/JS + nginx reverse-proxy config)
- `k8s/` — Deployment/Service manifests
- `deploy.sh` — builds the ConfigMaps from current source and applies everything
- `tests/break_test.sh` — resilience/chaos suite: `FRONTEND_URL=http://... bash tests/break_test.sh`
