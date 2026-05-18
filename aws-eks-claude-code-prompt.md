# CLAUDE CODE PROJECT PROMPT
# Self-Healing Kubernetes Cluster — AWS EKS + KAgent + Gemini
# Full GitHub Repository — Production-Grade Open Source
# =============================================================
# Read this entire file before writing a single line of code.
# This is the complete specification. Follow it exactly.

---

## PROJECT MISSION

Build and publish a **production-grade, open-source GitHub repository** for a
Self-Healing Kubernetes Cluster on AWS EKS, powered by KAgent as the AI agent
orchestrator and Google Gemini 2.5 Flash as the AI brain.

Every file must be something an experienced Platform Engineer would be proud
to open-source. The README must be a detailed, step-by-step operational guide
in the same style as this repo:
https://github.com/Abhiram-Rakesh/Three-Tier-EKS-Terraform

Study that README style carefully before writing the README:
- Every prerequisite has exact install commands with expected output
- Every step has a "Success indicator" block
- Expected command output is shown in code blocks
- Troubleshooting covers real failure modes with exact fix commands
- Teardown explains order-of-operations and why it matters

---

## REPOSITORY IDENTITY

```
Repo name:   self-healing-k8s-kagent
Tagline:     AI-powered Kubernetes self-healing using KAgent + Gemini on AWS EKS
Topics:      kubernetes, aws, eks, kagent, gemini, ai-agents, devops,
             platform-engineering, self-healing, prometheus, chaos-engineering,
             python, terraform, helm, cncf
License:     MIT
```

---

## ARCHITECTURE DECISIONS — READ BEFORE CODING

These are deliberate simplifications over a naive implementation:

**Memory store: SQLite, not ChromaDB**
Past incident memory uses a simple SQLite table. ChromaDB (vector DB) is
overkill when recall is always by exact `alert_type` key, not semantic
similarity. SQLite has zero extra dependencies and no external process.
Add ChromaDB only in a future V3 release if semantic search is needed.

**Secret management: boto3 direct fetch, not External Secrets Operator**
The agent pod uses IRSA to call AWS Secrets Manager via boto3 at startup.
This is the same security model as ESO (IRSA + Secrets Manager) with zero
extra operator components to install. ESO adds 3 setup steps for no
security gain in this context.

**Cost guard: request counter, not token counter**
Track `gemini_calls_today` as a simple integer. If calls exceed
`DAILY_REQUEST_LIMIT` (default 200), switch to notify_only mode.
Token counting via the SDK is asynchronous and unreliable — request
counting is deterministic and simpler.

**Predictive healing: Phase 2 only**
The Prometheus-polling predictor is excluded from Phase 1. Reactive healing
(alert fires → agent responds) must be solid before adding proactive paths.
The predictor is documented as a roadmap item.

**Runtime image: python:3.11-slim, not distroless**
Multi-stage build with python:3.11-slim runtime. Same security benefit of
stripping dev tools, without gcr.io registry dependency.

**CI/CD: two workflows, not three**
`ci.yml` handles lint + test + build + push.
`terraform.yml` handles plan on PR + apply on merge.
Release tagging is a job inside `ci.yml`.

---

## FULL REPOSITORY STRUCTURE

Create every file listed. No placeholders. No empty files. No TODOs in code.

```
self-healing-k8s-kagent/
│
├── .github/
│   ├── workflows/
│   │   ├── ci.yml
│   │   └── terraform.yml
│   ├── ISSUE_TEMPLATE/
│   │   ├── bug_report.md
│   │   └── feature_request.md
│   ├── PULL_REQUEST_TEMPLATE.md
│   └── CODEOWNERS
│
├── terraform/
│   ├── main.tf
│   ├── variables.tf
│   ├── outputs.tf
│   ├── versions.tf
│   ├── terraform.tfvars.example
│   └── modules/
│       ├── vpc/
│       │   ├── main.tf
│       │   ├── variables.tf
│       │   └── outputs.tf
│       ├── eks/
│       │   ├── main.tf
│       │   ├── variables.tf
│       │   └── outputs.tf
│       ├── ecr/
│       │   ├── main.tf
│       │   ├── variables.tf
│       │   └── outputs.tf
│       └── iam/
│           ├── main.tf
│           ├── variables.tf
│           └── outputs.tf
│
├── helm/
│   └── kagent-healer/
│       ├── Chart.yaml
│       ├── values.yaml
│       ├── values-prod.yaml
│       └── templates/
│           ├── _helpers.tpl
│           ├── deployment.yaml
│           ├── service.yaml
│           ├── serviceaccount.yaml
│           ├── clusterrole.yaml
│           ├── clusterrolebinding.yaml
│           ├── configmap.yaml
│           ├── servicemonitor.yaml
│           └── hpa.yaml
│
├── agent/
│   ├── main.py
│   ├── webhook_server.py
│   ├── gemini_client.py
│   ├── context_builder.py
│   ├── remediator.py
│   ├── memory.py
│   ├── cost_guard.py
│   ├── agents/
│   │   ├── __init__.py
│   │   ├── triage_agent.py
│   │   ├── diagnosis_agent.py
│   │   ├── remediation_agent.py
│   │   └── audit_agent.py
│   ├── tests/
│   │   ├── __init__.py
│   │   ├── test_gemini_client.py
│   │   ├── test_context_builder.py
│   │   ├── test_remediator.py
│   │   ├── test_triage_agent.py
│   │   └── test_webhook_server.py
│   └── requirements.txt
│
├── k8s/
│   ├── monitoring/
│   │   ├── alert-rules.yaml
│   │   ├── alertmanager-config.yaml
│   │   └── grafana-dashboard-configmap.yaml
│   ├── chaos/
│   │   ├── pod-delete-chaos.yaml
│   │   └── memory-hog-chaos.yaml
│   └── test-workloads/
│       ├── crash-loop.yaml
│       ├── oom-test.yaml
│       └── demo-app.yaml
│
├── scripts/
│   ├── demo.sh          # repeatable end-to-end demo with chaos injection
│   ├── teardown.sh      # safe ordered destroy — enforces critical teardown sequence
│   └── port-forward.sh  # opens all 5 service tunnels simultaneously
│
├── diagrams/
│   ├── high-level-flow.mmd
│   └── low-level-flow.mmd
│
├── Dockerfile
├── docker-compose.yml
├── .dockerignore
├── .env.example
├── .gitignore
├── .pre-commit-config.yaml
├── Makefile
├── pyproject.toml
├── LICENSE
└── README.md
```

---

## TERRAFORM SPECIFICATIONS

### `terraform/versions.tf`

```hcl
terraform {
  required_version = ">= 1.7"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.40"
    }
  }
  backend "s3" {
    key            = "self-healing-k8s/terraform.tfstate"
    encrypt        = true
    dynamodb_table = "terraform-state-lock"
  }
}

provider "aws" {
  region = var.aws_region
  default_tags {
    tags = var.tags
  }
}
```

### `terraform/variables.tf` — all variables with descriptions and defaults

```hcl
variable "aws_region"          { default = "us-east-1";              description = "AWS region for all resources" }
variable "cluster_name"        { default = "self-healing-cluster";    description = "EKS cluster name" }
variable "cluster_version"     { default = "1.32";                   description = "Kubernetes version" }
variable "environment"         { default = "dev";                    description = "dev | staging | prod" }
variable "system_node_type"    { default = "t3.medium";              description = "EC2 type for system node group" }
variable "workload_node_type"  { default = "t3.large";               description = "EC2 type for workload node group" }
variable "system_node_count"   { default = 2;                        description = "Node count for system group" }
variable "workload_node_count" { default = 2;                        description = "Node count for workload group" }
variable "enable_ha_nat"       { default = false;                    description = "true = 3 NAT GWs (HA), false = 1 (cost saving)" }
variable "state_bucket"        {                                      description = "S3 bucket name for Terraform state (must exist)" }
variable "gemini_api_key"      { sensitive  = true;                  description = "Google Gemini API key" }
variable "slack_webhook_url"   { default = "";  sensitive = true;    description = "Slack webhook URL for notifications (optional)" }
variable "tags" {
  default = {
    Project   = "self-healing-k8s-kagent"
    ManagedBy = "terraform"
  }
}
```

### VPC module (`terraform/modules/vpc/main.tf`)

- CIDR: `10.0.0.0/16`
- 3 AZs (use `data "aws_availability_zones"` — dynamic, not hardcoded)
- 3 private subnets: `10.0.1.0/24`, `10.0.2.0/24`, `10.0.3.0/24`
- 3 public subnets: `10.0.101.0/24`, `10.0.102.0/24`, `10.0.103.0/24`
- 1 Internet Gateway
- NAT Gateway: 1 if `enable_ha_nat = false`, 3 if true
- Subnet tags:
  - Private: `kubernetes.io/role/internal-elb = 1`
  - Public: `kubernetes.io/role/elb = 1`
  - Both: `kubernetes.io/cluster/${cluster_name} = shared`

### EKS module (`terraform/modules/eks/main.tf`)

- Cluster version: `var.cluster_version`
- Private endpoint: enabled; Public endpoint: enabled
- OIDC provider: enabled (required for IRSA)
- Two managed node groups:
  - `system`: `var.system_node_type`, `var.system_node_count`, OnDemand
  - `workload`: `var.workload_node_type`, `var.workload_node_count`, 70% OnDemand / 30% Spot
- Both node groups: 50GB gp3 EBS, encrypted, IMDSv2 required
- EKS Add-ons: coredns, kube-proxy, vpc-cni, aws-ebs-csi-driver
- Cluster logging enabled: api, audit, authenticator, controllerManager, scheduler

### ECR module (`terraform/modules/ecr/main.tf`)

- Repository: `kagent-healer`
- Image scanning on push: enabled
- Lifecycle policy: keep last 10 images, expire untagged after 7 days
- Encryption: AES256

### IAM module (`terraform/modules/iam/main.tf`)

IRSA role `kagent-healer-irsa`:
- Trust: OIDC provider → namespace `kagent` → SA `kagent-healer`
- Permissions:
  - `secretsmanager:GetSecretValue` on `arn:aws:secretsmanager:*:*:secret:kagent/*`
  - `logs:CreateLogGroup`, `logs:CreateLogStream`, `logs:PutLogEvents`
  - `cloudwatch:PutMetricData`

### `terraform/outputs.tf`

Output all of:
- `cluster_name`, `cluster_endpoint`, `kubeconfig_command`
- `ecr_repository_url`
- `kagent_irsa_role_arn`
- `vpc_id`, `private_subnet_ids`, `public_subnet_ids`
- `aws_account_id`

---

## PYTHON AGENT SPECIFICATIONS

### `agent/requirements.txt`

```
google-genai>=1.0.0
kubernetes>=29.0.0
python-dotenv>=1.0.0
prometheus-client>=0.20.0
requests>=2.31.0
boto3>=1.34.0
```

Note: No chromadb — memory uses SQLite (stdlib).

### `agent/gemini_client.py`

```python
"""
Gemini 2.5 Flash client for Kubernetes failure diagnosis.

Calls the Gemini API with structured prompts and returns
JSON remediation plans. Retries on rate limiting.
"""
```

- Model: `gemini-2.5-flash`
- API key: from `GEMINI_API_KEY` env var (fetched from Secrets Manager at startup)
- System prompt makes Gemini act as an expert Kubernetes SRE
- Response MUST be valid JSON matching this schema:
  ```json
  {
    "diagnosis": "root cause in one sentence",
    "action": "restart_pod | scale_up | cordon_node | notify_only | no_action",
    "target": "Deployment name — NEVER pod name",
    "target_namespace": "kubernetes namespace",
    "reason": "why this action resolves the root cause",
    "confidence": 0.85
  }
  ```
- System prompt rules:
  - `confidence < 0.70` → always return `notify_only`
  - `target` = Deployment name, never pod name
  - Never recommend deleting namespaces or cluster-scoped resources
  - Prefer least-disruptive action
- Past incident cases injected into prompt when memory has relevant entries
- Strip ```json fences before JSON parse
- Exponential backoff on 429: sleep 1s, 2s, 4s, 8s then give up
- On any parse error: return `notify_only` plan with `confidence=0.0`
- Log diagnosis + action + confidence at every call

### `agent/context_builder.py`

```python
"""
Builds Kubernetes context for Gemini diagnosis prompts.

Collects pod logs, events, pod state, and node conditions.
Never raises — always returns partial context on error.
"""
```

- `load_incluster_config()` first, fall back to `load_kube_config()`
- `build(alert: dict) -> dict` returns:
  - `alert_name`, `severity`, `pod_name`, `namespace`, `node_name`
  - `pod_logs`: 50 lines, `previous=True` first then current
  - `k8s_events`: 10 most recent events for the pod, desc by timestamp
  - `pod_describe`: container states, restart counts, resource limits/requests
  - `node_conditions`: all condition types and status for the pod's node
- Every field wrapped in try/except — returns `"Unavailable: {error}"` on failure

### `agent/remediator.py`

```python
"""
Executes Kubernetes healing actions with three safety gates.

Gate 1: Confidence threshold (default 0.75)
Gate 2: Protected namespace list
Gate 3: Dry-run mode (DRY_RUN env var)
"""
```

```python
CONFIDENCE_THRESHOLD = float(os.environ.get("CONFIDENCE_THRESHOLD", "0.75"))
MAX_REPLICAS = int(os.environ.get("MAX_REPLICAS", "10"))

PROTECTED_NAMESPACES = {
    "kube-system", "kube-public", "kube-node-lease",
    "monitoring", "litmus", "kagent",
    "external-secrets", "cert-manager",
    "aws-load-balancer-controller", "local-path-storage"
}
```

Actions:
- `restart_pod`: patch Deployment annotation `kubectl.kubernetes.io/restartedAt`
- `scale_up`: read current replicas → +1 → cap at `MAX_REPLICAS`
- `cordon_node`: patch node `spec.unschedulable = true`
- `notify_only` / `no_action`: no K8s change, return immediately

`execute(plan) -> dict` return shape:
```python
{
    "action": str,
    "target": str,
    "namespace": str,
    "confidence": float,
    "executed": bool,
    "reason": str,
    "dry_run": bool
}
```

### `agent/memory.py`

```python
"""
SQLite-backed incident memory for improving diagnosis accuracy.

Stores past incident outcomes so the agent can reference similar
cases when diagnosing new failures. Pure stdlib — no extra deps.
"""
```

Schema:
```sql
CREATE TABLE IF NOT EXISTS incidents (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    alert_type     TEXT NOT NULL,
    diagnosis      TEXT NOT NULL,
    action         TEXT NOT NULL,
    outcome        TEXT NOT NULL,
    confidence     REAL NOT NULL,
    created_at     TEXT NOT NULL
);
```

- DB path: `MEMORY_DB_PATH` env var, default `/tmp/kagent-memory.db`
- `store(entry: dict)`: insert row
- `recall(alert_type: str, limit: int = 3) -> str`: SELECT last N rows WHERE alert_type, format as readable string
- All operations wrapped in try/except — return `"Memory unavailable"` on error
- Thread-safe with `threading.Lock()`

### `agent/cost_guard.py`

```python
"""
Daily Gemini API request budget enforcer.

Counts API calls per day. When limit is reached, switches the
agent to notify-only mode until midnight UTC resets the counter.
"""
```

- `DAILY_REQUEST_LIMIT`: from env, default `200`
- `check_and_increment() -> bool`: returns True if call is allowed
- Resets at midnight UTC
- Thread-safe with `threading.Lock()`
- Logs warning at 80% of limit, error when limit reached

### `agent/agents/triage_agent.py`

```python
"""
First stage of the healing pipeline.

Deduplicates alerts (5-minute TTL) and classifies severity.
Returns None for duplicates so they are silently dropped.
"""
```

- Dedup key: `{alertname}:{namespace}:{pod}`
- TTL: 300 seconds
- Severity weights: `critical=3`, `warning=2`, `info=1`
- Returns `None` for duplicates, `triage_result` dict for new alerts

### `agent/agents/diagnosis_agent.py`

```python
"""
Second stage: builds context and calls Gemini for diagnosis.
"""
```

- Calls `ContextBuilder.build(alert)`
- Calls `RunbookMemory.recall(alert_type)` — injects into Gemini prompt
- Calls `CostGuard.check_and_increment()` — if False, returns notify_only plan
- Calls `GeminiClient.diagnose(context)`

### `agent/agents/remediation_agent.py`

```python
"""
Third stage: executes the healing action with safety gates.

High-impact actions (cordon_node) require HITL approval via Slack.
Auto-approves after 300s if no response received.
"""
```

```python
REQUIRES_APPROVAL = {"cordon_node"}
APPROVAL_TIMEOUT_SECONDS = 300
```

### `agent/agents/audit_agent.py`

```python
"""
Final stage: records every healing event and sends notifications.
"""
```

- JSONL audit log: `/tmp/kagent-audit.jsonl`
- Fields: `timestamp`, `alert_key`, `severity`, `diagnosis`, `action`,
  `target`, `namespace`, `confidence`, `executed`, `outcome`, `dry_run`
- Slack notification via `SLACK_WEBHOOK_URL` env var (optional)
- CloudWatch custom metric: `KAgent/HealingEvents` — dimensions: Action, Executed

### `agent/main.py`

```python
"""
Entry point. Starts metric server, loads secrets, starts webhook server.
"""
```

Startup sequence:
1. Load secrets from AWS Secrets Manager if running in-cluster
   (detect via `KUBERNETES_SERVICE_HOST` env var)
2. Start Prometheus metrics HTTP server on port 8001
3. Start `WebhookServer` on port 8000

Custom metrics:
```python
alerts_total       = Counter("kagent_alerts_total", "Alerts received", ["severity"])
gemini_calls_total = Counter("kagent_gemini_calls_total", "Gemini API calls")
actions_total      = Counter("kagent_actions_total", "Actions executed", ["action", "executed"])
healing_seconds    = Histogram("kagent_healing_seconds", "Alert to resolution time")
confidence_gauge   = Gauge("kagent_last_confidence", "Last Gemini confidence score")
budget_remaining   = Gauge("kagent_requests_remaining_today", "Remaining daily Gemini requests")
```

### `agent/webhook_server.py`

```python
"""
HTTP server receiving Alertmanager webhook POSTs.

Returns 200 immediately, processes alerts asynchronously.
Pipeline: triage → diagnosis → remediation → audit.
"""
```

- `GET /health` → `200 {"status":"ok","version":"1.0.0"}`
- `POST /webhook` → `200` immediately, process in background thread
- Skip `status=resolved` alerts
- Full pipeline: triage → diagnosis → remediation → audit
- Log full result at INFO

---

## HELM CHART SPECIFICATIONS

### `helm/kagent-healer/Chart.yaml`

```yaml
apiVersion: v2
name: kagent-healer
description: AI-powered Kubernetes self-healing agent using KAgent and Gemini
type: application
version: 0.1.0
appVersion: "1.0.0"
keywords: [kagent, gemini, self-healing, kubernetes, ai-agents]
home: https://github.com/YOUR_USERNAME/self-healing-k8s-kagent
```

### `helm/kagent-healer/values.yaml`

```yaml
replicaCount: 1

image:
  repository: ""
  tag: "latest"
  pullPolicy: Always

serviceAccount:
  create: true
  name: kagent-healer
  annotations: {}      # IRSA role ARN set at deploy time

agent:
  dryRun: "true"       # ALWAYS default true — explicit override required
  confidenceThreshold: "0.75"
  maxReplicas: "10"
  dailyRequestLimit: "200"
  memoryDbPath: "/tmp/kagent-memory.db"
  secretsManagerRegion: "us-east-1"
  geminiApiKeySecret: "kagent/gemini-api-key"
  slackWebhookSecret: "kagent/slack-webhook"

resources:
  requests:
    cpu: 100m
    memory: 256Mi
  limits:
    cpu: 500m
    memory: 512Mi

service:
  webhookPort: 8000
  metricsPort: 8001

serviceMonitor:
  enabled: true
  interval: 15s

hpa:
  enabled: false
  minReplicas: 1
  maxReplicas: 3
  targetCPUUtilizationPercentage: 70
```

---

## KUBERNETES MANIFEST SPECIFICATIONS

### `k8s/monitoring/alert-rules.yaml`

PrometheusRule CRD, namespace `monitoring`, label `release: monitoring`

5 alert rules in group `kagent.healing` (interval 30s), all labelled `kagent: "true"`:

1. `PodCrashLooping`
   `rate(kube_pod_container_status_restarts_total[5m]) * 60 > 0.5` for 1m, critical

2. `PodOOMKilled`
   `kube_pod_container_status_last_terminated_reason{reason="OOMKilled"} == 1` for 0m, critical

3. `PodPendingTooLong`
   `kube_pod_status_phase{phase="Pending"} == 1` for 5m, warning

4. `NodeNotReady`
   `kube_node_status_condition{condition="Ready",status="true"} == 0` for 2m, critical

5. `PVCUsageHigh`
   `kubelet_volume_stats_used_bytes / kubelet_volume_stats_capacity_bytes > 0.85` for 5m, warning

Each annotation must include `pod: "{{ $labels.pod }}"` and `namespace: "{{ $labels.namespace }}"` for the context builder to extract from the alert.

### `k8s/monitoring/grafana-dashboard-configmap.yaml`

ConfigMap with complete Grafana dashboard JSON. Dashboard panels:
- 4 stat panels: alerts received, actions executed, avg confidence, avg MTTR
- 2 time series: alert rate over time, healing duration p50/p95
- 1 time series: Gemini confidence scores
- 1 pie chart: actions by type
- 1 pie chart: alerts by severity
- 1 table: recent healing events (last 20), sorted by timestamp desc

Label the ConfigMap with `grafana_dashboard: "1"` so Grafana sidecar auto-imports it.

### `k8s/test-workloads/crash-loop.yaml`

```yaml
# Deployment in namespace default
# image: busybox
# command: echo Starting; sleep 5; echo Crashing; exit 1
# limits: memory 64Mi, cpu 50m
```

### `k8s/test-workloads/oom-test.yaml`

```yaml
# Deployment in namespace default
# image: polinux/stress
# command: stress --vm 1 --vm-bytes 150M --vm-hang 1
# limits: memory 64Mi  ← lower than usage = guaranteed OOMKill
```

### `k8s/test-workloads/demo-app.yaml`

```yaml
# Deployment in namespace default, 2 replicas
# image: nginx:alpine
# limits: memory 64Mi, cpu 100m
# Used as chaos experiment target
```

---

## CI/CD SPECIFICATIONS

### `.github/workflows/ci.yml`

Triggers: push to any branch, PR to main

```yaml
permissions:
  id-token: write
  contents: read
  pull-requests: write
```

Jobs:
1. `lint` — ruff, black --check, mypy (ignore missing imports)
2. `test` — pytest with coverage, upload to Codecov
3. `lint-infra` — terraform fmt -check, hadolint
4. `build-push` (on push to main only):
   - Configure AWS via OIDC (no static keys)
   - Login to ECR
   - Build linux/amd64 image
   - Push SHA tag + `latest`
   - Trivy scan, fail on CRITICAL
5. `release` (on push of tag `v*.*.*`):
   - Create GitHub Release with changelog
   - Push version-tagged image

### `.github/workflows/terraform.yml`

Triggers: PR or push touching `terraform/**`

```yaml
permissions:
  id-token: write
  contents: read
  pull-requests: write
```

Jobs:
1. `plan` — init, validate, plan, post plan as PR comment
2. `apply` — on merge to main only, apply saved plan

---

## SCRIPTS SPECIFICATIONS

All scripts must start with:
```bash
#!/bin/bash
set -euo pipefail
```

## SCRIPTS PHILOSOPHY

bootstrap.sh, setup-secrets.sh, and deploy.sh are intentionally NOT included.
All setup commands are written as explicit README steps that the user types
manually. This is a deliberate portfolio decision:

- Explicit steps in the README show understanding — a bootstrap script hides it
- Users learn the system by following steps, not by running a wrapper
- The Three-Tier-EKS-Terraform README style proves this approach works

The three scripts that DO exist serve distinct operational purposes that
genuinely benefit from automation:
- demo.sh: a repeatable showcase — timing and sequencing matters for a demo
- teardown.sh: enforces critical teardown order to prevent stuck AWS state
- port-forward.sh: opens 5 simultaneous tunnels — a day-2 convenience

### `scripts/demo.sh`

Complete end-to-end demonstration:
1. Print cluster health (kubectl get nodes, pods -n kagent)
2. Deploy crash-loop workload
3. Wait for PodCrashLooping alert (3 min timeout with spinner)
4. Tail agent logs until healing action logged
5. Print final pod state + audit log tail
6. Deploy OOM test workload, repeat
7. Run Litmus pod-delete experiment on demo-app
8. Print full audit log summary
9. Clean up all test workloads
10. Print Grafana URL

### `scripts/teardown.sh`

Requires typed confirmation: "yes I want to destroy everything"

Order:
1. Uninstall all Helm releases
2. Delete all namespaces (triggers LB cleanup)
3. Wait 60s for AWS to clean up ENIs
4. Force-delete any remaining ELBs in the VPC
5. terraform destroy

### `scripts/port-forward.sh`

Opens port forwards for all services, binds to `0.0.0.0` so accessible
from the local network. Prints URLs after opening.

---

## DOCKERFILE

```dockerfile
# Stage 1: builder
FROM python:3.11-slim AS builder
WORKDIR /app
COPY agent/requirements.txt .
RUN pip install --no-cache-dir --user -r requirements.txt

# Stage 2: runtime
FROM python:3.11-slim
WORKDIR /app
COPY --from=builder /root/.local /root/.local
COPY agent/ .
ENV PATH=/root/.local/bin:$PATH \
    PORT=8000 \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1
EXPOSE 8000 8001
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')"
CMD ["python", "main.py"]
```

---

## MAKEFILE

```makefile
.DEFAULT_GOAL := help

help: ## Show available targets
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
	  awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2}'

install: ## Install Python dev dependencies
	pip install -r agent/requirements.txt
	pip install ruff black mypy pytest pytest-cov

lint: ## Run all linters
	ruff check agent/
	black --check agent/
	mypy agent/ --ignore-missing-imports
	terraform fmt -check terraform/ || true
	hadolint Dockerfile || true

test: ## Run tests with coverage
	pytest agent/tests/ -v --cov=agent --cov-report=term-missing

build: ## Build Docker image
	docker build -t kagent-healer:local .

run: ## Run agent locally (requires .env)
	docker-compose up

demo: ## Run end-to-end demo (chaos injection + healing loop)
	./scripts/demo.sh

port-forward: ## Open all service tunnels (Grafana, Prometheus, Alertmanager, KAgent UI)
	./scripts/port-forward.sh

teardown: ## Destroy everything in correct order (asks for confirmation)
	./scripts/teardown.sh

.PHONY: help install lint test build run demo port-forward teardown
```

---

## PYPROJECT.TOML

```toml
[tool.black]
line-length = 88
target-version = ['py311']

[tool.ruff]
line-length = 88
select = ["E", "F", "I", "N", "W", "B", "UP"]
ignore = ["E501"]

[tool.pytest.ini_options]
testpaths = ["agent/tests"]
addopts = "-v --cov=agent --cov-report=term-missing"

[tool.mypy]
python_version = "3.11"
warn_return_any = true
warn_unused_configs = true
```

---

## README.md — DETAILED SPECIFICATION

**This is the most important file in the repo. Write it last.**
Follow the exact style of https://github.com/Abhiram-Rakesh/Three-Tier-EKS-Terraform:
- Every prerequisite has exact install commands and expected output
- Every deployment step has a "Success indicator:" block
- Expected command output shown verbatim in code blocks
- Troubleshooting covers real failure modes with exact fix commands
- No hand-waving — if a step requires a specific flag or order, explain why

### README structure (write in this order):

```markdown
# Self-Healing Kubernetes Cluster with KAgent + Gemini AI

[badge row]

[one-line description]

---

## Architecture diagram
[Mermaid high-level flowchart]

---

## Tech stack
[table: Layer | Technology | Purpose]

---

## Prerequisites

### 1. AWS CLI v2
[exact install commands for Linux/macOS/Windows]
[aws configure commands with example output]
Verify: aws sts get-caller-identity shows your Account ID

### 2. Terraform >= 1.7
[exact install commands]
Verify: terraform --version shows 1.7+

### 3. kubectl
[exact install commands pinned to K8s 1.32]
Verify: kubectl version --client

### 4. Helm v3
[exact install commands]
Verify: helm version

### 5. Docker
[exact install commands]
Verify: docker run hello-world

### 6. Google Gemini API key
Get your free API key from https://aistudio.google.com
Verify: curl -s "https://generativelanguage.googleapis.com/v1beta/models?key=YOUR_KEY" | jq '.models[0].name'

### AWS IAM requirements
[table: Policy | Why needed]

---

## Deployment — step by step

### Step 1 — Fork and clone the repository
[git clone command]
Expected output:
[exact clone output]
Success indicator: ls shows Makefile, terraform/, agent/

### Step 2 — Create Terraform state bucket
[aws s3api create-bucket command]
[aws s3api put-bucket-versioning command]
[aws dynamodb create-table command for state lock]
Success indicator: aws s3 ls shows the bucket

### Step 3 — Configure and provision infrastructure
[cp terraform.tfvars.example terraform/terraform.tfvars]
[explain each variable to set]
[terraform init, plan, apply commands]
Expected output (last lines of apply):
[exact output block with all Outputs:]
[export shell variables from terraform output]
Success indicator: aws eks list-clusters shows self-healing-cluster

### Step 4 — Configure kubectl
[aws eks update-kubeconfig command]
[kubectl get nodes command]
Expected output:
[exact node output with STATUS=Ready]
Success indicator: Both nodes show STATUS=Ready

### Step 5 — Install cluster add-ons

#### 5a — Metrics Server
[kubectl apply command]
[kubectl top nodes to verify]
Expected output: [node CPU/memory table]
Success indicator: kubectl top nodes shows percentages

#### 5b — kube-prometheus-stack
[helm repo add + helm upgrade --install command with all values]
[kubectl get pods -n monitoring to verify]
Success indicator: All monitoring pods show Running

#### 5c — Litmus ChaosCenter
[helm install command]
Success indicator: kubectl get pods -n litmus shows Running

#### 5d — KAgent
[helm install kagent-crds command]
[sleep 15]
[helm install kagent command with --set providers.default=gemini]
[kubectl get pods -n kagent to verify]
Success indicator: All kagent pods show Running

### Step 6 — Push secrets to AWS Secrets Manager
[export GEMINI_API_KEY=...]
[aws secretsmanager put-secret-value commands — typed manually, shown in Step 6]
Expected output: Secret kagent/gemini-api-key created
Success indicator: aws secretsmanager get-secret-value --secret-id kagent/gemini-api-key returns your key

### Step 7 — Apply alert rules and Grafana dashboard
[kubectl apply -f k8s/monitoring/alert-rules.yaml]
[kubectl apply -f k8s/monitoring/alertmanager-config.yaml]
[kubectl apply -f k8s/monitoring/grafana-dashboard-configmap.yaml]
Verify: kubectl get prometheusrule -n monitoring
Expected: kagent-healer-rules appears
Success indicator: 5 alert rules visible at http://<GRAFANA_LB>:80/alerting/list

### Step 8 — Build and push agent image

Show the exact commands the user types:

```bash
# Get ECR URL from Terraform output
export ECR_URL=$(terraform -chdir=terraform output -raw ecr_repository_url)
export AWS_ACCOUNT_ID=$(terraform -chdir=terraform output -raw aws_account_id)
echo "ECR: ${ECR_URL}"

# Authenticate Docker to ECR
aws ecr get-login-password --region us-east-1 | \
  docker login --username AWS --password-stdin ${ECR_URL}

# Build the agent image
docker build -t kagent-healer:latest .

# Tag and push
docker tag kagent-healer:latest ${ECR_URL}:latest
docker push ${ECR_URL}:latest
```

Expected output (last lines):
```
latest: digest: sha256:abc123... size: 1234
```

Verify image is in ECR:
```bash
aws ecr describe-images --repository-name kagent-healer --region us-east-1 \
  --query 'imageDetails[*].{Tag:imageTags[0],Pushed:imagePushedAt,Size:imageSizeInBytes}'
```

Success indicator: Image appears with tag `latest` and a recent push timestamp

### Step 9 — Deploy the healer agent

```bash
# Get IRSA role ARN from Terraform output
export KAGENT_IRSA_ARN=$(terraform -chdir=terraform output -raw kagent_irsa_role_arn)
export ECR_URL=$(terraform -chdir=terraform output -raw ecr_repository_url)

# Deploy via Helm
helm upgrade --install kagent-healer helm/kagent-healer/ \
  --namespace kagent \
  --create-namespace \
  --set image.repository=${ECR_URL} \
  --set image.tag=latest \
  --set serviceAccount.annotations."eks\.amazonaws\.com/role-arn"=${KAGENT_IRSA_ARN} \
  --set agent.dryRun="true" \
  --wait

# Watch the pod come up
kubectl get pods -n kagent -w
```

Expected output:
```
NAME                             READY   STATUS    RESTARTS   AGE
kagent-healer-6d8f9b7c4-xk2pv   2/2     Running   0          45s
```

Verify the health endpoint:
```bash
# Get a worker node IP
NODE_IP=$(kubectl get nodes -o wide | grep -v master | awk 'NR==2{print $6}')
curl http://${NODE_IP}:30000/health
```

Expected response:
```json
{"status":"ok","version":"1.0.0"}
```

Success indicator: Pod shows `2/2 Running` and health check returns `{"status":"ok"}`

### Step 10 — Verify end-to-end healing loop
[kubectl apply -f k8s/test-workloads/crash-loop.yaml]
[watch kubectl get pods]
[kubectl logs -n kagent -l app=kagent-healer -f to watch diagnosis]
Expected agent log output:
[exact log lines showing alert received → diagnosis → action]
Success indicator: Agent log shows Successfully executed restart_pod

---

## Running the demo
```bash
./scripts/demo.sh
```

The demo script runs automatically but show what each phase does so the reader
understands what they are watching:
1. Cluster health check — verifies all nodes and KAgent pods are Running
2. Crash-loop injection — deploys a pod that intentionally exits with code 1
3. Alert firing — waits for PodCrashLooping alert (up to 3 minutes, shows spinner)
4. Gemini diagnosis — shows real-time agent logs with diagnosis + confidence score
5. Healing action — shows the restart_pod action being executed
6. OOM injection — deploys a pod that immediately exceeds its memory limit
7. Litmus chaos — runs a pod-delete experiment on the demo-app
8. Audit summary — prints the full healing event log
9. Cleanup — removes all test workloads

---

## Healing actions reference
[table: Alert | Trigger | Action | Confidence needed | What happens]

---

## Configuration reference
[table: Env var | Helm value | Description | Default | Required]

---

## Custom alert rules
[explain how to add rules to alert-rules.yaml]
[example custom rule]

---

## Enabling live healing (DRY_RUN=false)
[explain the dry-run mode]
[helm upgrade command to disable dry-run]
[what to watch to confirm it's working]

---

## AWS cost estimate
[table: Service | Dev (spin up/down) | Always-on dev | Notes]
EKS control plane: $0.10/hr / ~$73/mo
EC2 t3.medium×2: $0.08/hr total / ~$60/mo
EC2 t3.large×2: $0.16/hr total / ~$116/mo
NAT Gateway: $0.045/hr / ~$33/mo
ECR: ~$1/mo
Secrets Manager: $1.20/mo (3 secrets)
Gemini API: free tier
Total: ~$4–6 per session / ~$285/mo always-on
[see Teardown section — run commands in the documented order]

---

## Day-2 operations

### View agent logs
[kubectl logs command]

### Check audit log
[kubectl exec command to cat /tmp/kagent-audit.jsonl | jq]

### Manually test healing
[kubectl apply crash-loop]
[watch healing loop execute]
[kubectl delete deployment crash-test when done]

### Rolling restart
[kubectl rollout restart deployment/kagent-healer -n kagent]

### Update Gemini API key
[aws secretsmanager update-secret command]
[kubectl rollout restart to pick up new key]

---

## Troubleshooting

### 1. Agent pod not starting — CrashLoopBackOff
Symptom: [exact kubectl get pods output]
Diagnosis: [kubectl describe + kubectl logs --previous commands]
Fix: [step by step fix with verification command]
Success indicator: [exact healthy output]

### 2. Alerts not reaching the agent
Symptom: Alerts fire in Prometheus but agent logs show nothing
Diagnosis: [kubectl describe alertmanagerconfig command]
Fix: [exact fix with verification]

### 3. Gemini returns low confidence (below 0.75)
Symptom: Agent logs show notify_only repeatedly
Diagnosis: The context builder may be returning empty logs/events
Fix: [kubectl exec into agent pod to test context building manually]

### 4. PVC pending — no StorageClass
[same issue we hit — link to local-path-provisioner install]

### 5. kubectl logs failing — pod networking issue
[Calico BGP fix we discovered — exact commands]

### 6. DRY_RUN=false but no actions executing
[check PROTECTED_NAMESPACES, check confidence threshold]

### 7. Gemini API key invalid
[how to verify the key, how to update it in Secrets Manager]

### 8. ECR push denied
[IAM policy check, ecr get-login-password verification]

---

## Teardown
```bash
./scripts/teardown.sh
```

The script enforces this exact order — explain why in the README:

1. Uninstall all Helm releases (triggers controller cleanup of AWS LBs and target groups)
2. Delete namespaces (removes remaining workloads and PVCs)
3. Wait 60 seconds (AWS needs time to detach and delete ENIs from subnets)
4. Force-delete any ELBs and NLBs remaining in the VPC (Kubernetes controllers sometimes miss these)
5. terraform destroy

**Why order matters:** Terraform cannot delete the VPC while any ENIs remain in its
subnets. Steps 1-4 ensure every Load Balancer, Target Group, and ENI is gone before
Terraform runs. Skipping this order causes `terraform destroy` to hang on VPC deletion
for 15+ minutes before failing.

If `teardown.sh` fails at step 5, show the manual recovery commands:
```bash
# List remaining LBs in the VPC
VPC_ID=$(terraform -chdir=terraform output -raw vpc_id)
aws elbv2 describe-load-balancers --region us-east-1 \
  --query "LoadBalancers[?VpcId=='${VPC_ID}'].LoadBalancerArn" --output text

# Delete each one manually then re-run terraform destroy
aws elbv2 delete-load-balancer --region us-east-1 --load-balancer-arn <ARN>
sleep 60
terraform -chdir=terraform destroy
```

---

## Roadmap
- [ ] V2: Slack HITL approval with interactive buttons
- [ ] V2: Grafana live healing dashboard
- [ ] V2: Litmus chaos scheduled experiments
- [ ] V3: ChromaDB semantic memory (replace SQLite)
- [ ] V3: Predictive healing via Prometheus trend polling
- [ ] V3: Multi-cluster support
- [ ] V3: KAgent A2A multi-agent delegation

---

## Contributing
[link to .github/PULL_REQUEST_TEMPLATE.md]
[how to add a new healing action — step by step]
[how to add a new alert rule]
[testing guide: make test]

---

## License
MIT
```

### Badges (first line of README after the title):

```markdown
![CI](https://github.com/YOUR_USERNAME/self-healing-k8s-kagent/actions/workflows/ci.yml/badge.svg)
![Terraform](https://github.com/YOUR_USERNAME/self-healing-k8s-kagent/actions/workflows/terraform.yml/badge.svg)
![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)
![Kubernetes](https://img.shields.io/badge/kubernetes-1.32-326CE5?logo=kubernetes&logoColor=white)
![Python](https://img.shields.io/badge/python-3.11-3776AB?logo=python&logoColor=white)
![Terraform](https://img.shields.io/badge/terraform-1.7+-7B42BC?logo=terraform&logoColor=white)
![AWS EKS](https://img.shields.io/badge/AWS-EKS-FF9900?logo=amazon-aws&logoColor=white)
![CNCF Sandbox](https://img.shields.io/badge/CNCF-Sandbox-0086FF?logo=cncf&logoColor=white)
```

---

## TESTS SPECIFICATION

All tests use `unittest.mock`. Zero real K8s or Gemini calls.

### `agent/tests/test_gemini_client.py`

- Valid JSON response parsed correctly
- Markdown fences stripped before parse
- JSON parse error → notify_only fallback with confidence 0.0
- 429 response → retries with backoff (mock time.sleep)
- Past cases injected into prompt when memory provides them

### `agent/tests/test_remediator.py`

- Confidence below threshold → notify_only, executed=False
- Protected namespace → blocked, executed=False, reason contains "protected"
- dry_run=True → log only, executed=True, dry_run=True in result
- restart_pod patches correct annotation key
- scale_up increments replicas by 1
- scale_up respects MAX_REPLICAS ceiling

### `agent/tests/test_triage_agent.py`

- First alert of a type passes through
- Duplicate within TTL → None
- Duplicate after TTL expires → passes through
- Severity weights correct

### `agent/tests/test_webhook_server.py`

- GET /health → 200 with status ok
- POST /webhook → 200 immediately (async processing)
- Resolved alerts skipped
- Malformed JSON body → 400

### `agent/tests/test_context_builder.py`

- Pod logs fetched with previous=True first
- Falls back to current logs if previous unavailable
- Returns "Unavailable: ..." string on K8s API error (never raises)
- Events sorted by timestamp descending

---

## QUALITY STANDARDS

Every Python file:
- Module-level docstring explaining purpose
- Type hints on all function signatures
- `logging` not `print`
- All K8s API calls wrapped in try/except
- No hardcoded secrets

Every Terraform file:
- `description` on every variable and output
- `tags` applied to every resource

Every K8s manifest:
- `namespace` explicitly set
- `resources.requests` AND `resources.limits`
- `app.kubernetes.io/*` labels (name, instance, component, managed-by)
- No `latest` image tag in prod manifests (SHA tag in CI, `latest` only in local dev values)

Every GitHub Actions workflow:
- `permissions:` block (least privilege)
- `timeout-minutes:` set on every job
- No hardcoded secrets — all from `${{ secrets.* }}`
- OIDC for AWS auth — no long-lived IAM access keys in secrets

Every shell script:
- `#!/bin/bash` shebang
- `set -euo pipefail`
- Colored status output (green for OK, red for error)
- `Success indicator:` comment after each major step

---

## BUILD ORDER

Build in this exact sequence — each depends on the previous:

1. `.gitignore`, `LICENSE`, `.env.example`, `.dockerignore`
2. `pyproject.toml`, `.pre-commit-config.yaml`
3. `Makefile`
4. `Dockerfile`, `docker-compose.yml`
5. `agent/requirements.txt`
6. Agent code: `memory.py` → `cost_guard.py` → `gemini_client.py` → `context_builder.py` → `remediator.py`
7. Agent pipeline: `agents/triage_agent.py` → `agents/diagnosis_agent.py` → `agents/remediation_agent.py` → `agents/audit_agent.py`
8. `agent/webhook_server.py` → `agent/main.py`
9. All `agent/tests/` files
10. All `terraform/` files (versions → variables → modules → main → outputs)
11. All `helm/` chart files
12. All `k8s/` manifests
13. `scripts/demo.sh`, `scripts/teardown.sh`, `scripts/port-forward.sh`
14. `.github/` workflows
15. `diagrams/` mermaid files
16. `README.md` — written last when everything else is real

---

## FINAL CHECKLIST

```
[ ] No hardcoded API keys, account IDs, ARNs, or passwords
[ ] terraform.tfvars.example has example values but no real values
[ ] All Python files: ruff passes, black passes, mypy passes
[ ] All tests pass: pytest agent/tests/ with >80% coverage
[ ] All Terraform: terraform fmt passes, terraform validate passes
[ ] Dockerfile builds: docker build . succeeds
[ ] All shell scripts: shellcheck passes (no warnings)
[ ] All K8s manifests: resources.requests AND resources.limits set
[ ] DRY_RUN="true" is the default in values.yaml
[ ] PROTECTED_NAMESPACES includes aws-load-balancer-controller
[ ] .gitignore covers .env, terraform.tfvars, kubeconfig, __pycache__
[ ] README has a Success indicator for every deployment step
[ ] README troubleshooting covers at least 8 real failure modes
[ ] README teardown explains why order matters
[ ] Makefile help target lists all targets with descriptions
[ ] Both Mermaid diagram files in diagrams/ directory
[ ] LICENSE has current year and correct name
[ ] demo.sh runs end-to-end without errors on a clean cluster
[ ] teardown.sh requires typed confirmation before destroying anything
[ ] All GitHub Actions use OIDC for AWS (no static IAM keys)
[ ] CI workflow runs on every push to every branch
[ ] Terraform workflow only applies on merge to main
```
