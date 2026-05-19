# Build Prompt: Self-Healing Kubernetes Agent with MCP-Native Architecture

## What you are building

An AI-powered self-healing platform for Amazon EKS. Prometheus fires alerts to a Python webhook server. The webhook hands each alert to Gemini 2.5 Flash, which drives its own investigation and remediation entirely through MCP tool calls — reading Kubernetes state, executing safe healing actions, and recording the outcome — without any orchestration code in between.

This is a **full rebuild from scratch**. Do not copy or reference any previous implementation. Follow this specification exactly.

---

## Non-negotiable constraints

- **Language:** Python 3.11
- **LLM:** Gemini 2.5 Flash via `google-genai>=1.0.0`
- **MCP framework:** `mcp>=1.0.0` (FastMCP)
- **Kubernetes client:** `kubernetes>=29.0.0`
- **Cloud:** AWS EKS, ECR, Secrets Manager, CloudWatch
- **Packaging:** Helm v3 chart at `helm/kagent-healer/`
- **Infrastructure:** Terraform at `terraform/` — **do not touch**
- **CI:** GitHub Actions at `.github/workflows/ci.yml` — update only test file references
- **README style:** Keep all existing sections, formatting, badge style, and tone — update content only where the architecture changes

---

## Core architectural principle

**Gemini is the orchestrator. Your code is the toolbox.**

All external I/O lives in one file: `agent/mcp_server.py`. Every Kubernetes read, every healing action, every audit write is an MCP tool. Gemini calls those tools in whatever order it decides, then calls `record_outcome` to conclude. Your pipeline code only triages (deduplication) and hands the alert to Gemini. Nothing else.

There is no ContextBuilder class. There is no Remediator class. There are no separate Agent classes for diagnosis, remediation, and audit. Those abstractions belong to the old single-shot design where Gemini had no agency. In this design, Gemini has full agency.

---

## Repository structure after the rebuild

### Files to create (the entire agent/ folder is new)

```
agent/
  __init__.py
  mcp_server.py      all Kubernetes + SQLite + Slack + CloudWatch interactions
  gemini.py          Gemini client with MCP tool-calling loop
  pipeline.py        triage (dedup) + run (hands alert to Gemini)
  server.py          webhook HTTP server + /approve/<id> + /health
  cost_guard.py      daily Gemini request budget enforcer
  main.py            startup: secrets, metrics, wiring, serve
  tests/
    __init__.py
    conftest.py
    test_mcp_server.py
    test_gemini.py
    test_pipeline.py
    test_server.py
```

### Files to update (minimal changes)

```
helm/kagent-healer/templates/configmap.yaml   add GEMINI_MAX_TURNS
helm/kagent-healer/values.yaml                add geminiMaxTurns field
diagrams/low-level-flow.mmd                   rewrite to show Gemini tool-calling loop
README.md                                     update architecture, tech stack, config reference
.env.example                                  add GEMINI_MAX_TURNS
```

### Files to leave completely unchanged

```
terraform/                    all infrastructure
helm/kagent-healer/templates/ (except configmap.yaml)
helm/kagent-healer/values-prod.yaml
helm/kagent-healer/Chart.yaml
.github/workflows/ci.yml      (only update test file name references)
.github/                      PR template, dependabot
Dockerfile
pyproject.toml
scripts/
SECURITY.md
CONTRIBUTING.md
```

---

## Specification: `agent/mcp_server.py`

This is the most important file. It is a FastMCP server that exposes every external interaction as a tool. It also holds the module-level state for SQLite, the approval store, and scale tracking.

### Module-level state

```
_core          kubernetes CoreV1Api  — set by init()
_apps          kubernetes AppsV1Api  — set by init()
_db_path       str                   — set by init(), default /tmp/kagent-memory.db
_audit_path    str                   — set by init(), default /tmp/kagent-audit.jsonl
_slack_url     str                   — set by init(), default ""
_cw_client     boto3 CloudWatch      — set by init(), None if not in-cluster
_approval_store ApprovalStore        — module-level singleton
_scale_state   dict[str, tuple[str, str, int]]  alert_key → (ns, deployment, original_replicas)
_scale_lock    threading.Lock
```

### `init()` function

```python
def init(
    core_api,
    apps_api,
    db_path: str,
    audit_path: str,
    slack_url: str,
    aws_region: str,
) -> None
```

Sets all module-level state. Initialises the SQLite schema. Initialises the CloudWatch boto3 client only if `KUBERNETES_SERVICE_HOST` env var is set (in-cluster detection). Never raises — log errors and continue.

### SQLite schema

One table named `incidents`:

```sql
CREATE TABLE IF NOT EXISTS incidents (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    alert_type TEXT NOT NULL,
    diagnosis  TEXT NOT NULL,
    action     TEXT NOT NULL,
    outcome    TEXT NOT NULL,
    confidence REAL NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_alert_type ON incidents(alert_type);
```

Use a module-level `threading.Lock` for all SQLite reads and writes.

### `ApprovalStore` class

Thread-safe store of pending HITL approvals.

```python
class ApprovalStore:
    register(action_id: str) -> threading.Event
    approve(action_id: str) -> bool   # returns False if unknown or already consumed
    cancel(action_id: str) -> None
    pending_ids() -> list[str]
```

`approve()` pops the entry from `_pending`, sets the event, and returns True. If the key is not found, returns False. This prevents double-approval.

### MCP tools — read (investigation)

Register all six with `@mcp.tool()`. Each calls the Kubernetes API and returns a formatted string. Every tool handles its own exceptions — return `"Unavailable: <reason>"` on error, never raise.

**`get_pod_logs(namespace: str, pod: str) -> str`**
Try `previous=True` first (crash-loop case), fall back to `previous=False`. Return last 50 lines labelled `[previous]` or `[current]`. If both fail, return `"Unavailable: no logs"`.

**`get_pod_events(namespace: str, pod: str) -> str`**
List events with `field_selector=involvedObject.name={pod}`. Sort descending by `last_timestamp`. Return the 10 most recent as JSON. Return `"No events found."` if empty.

**`describe_pod(namespace: str, pod: str) -> str`**
Return JSON with: `phase`, `node` (node_name), `containers` (name, image, resources), `containerStatuses` (name, ready, restartCount, state). Return `"Unavailable: <reason>"` on error.

**`get_node_conditions(node_name: str) -> str`**
Return JSON array of node conditions: `type`, `status`, `reason`, `message`. Return `"Unavailable: <reason>"` on error.

**`resolve_deployment(namespace: str, pod: str) -> str`**
Walk ownerReferences: Pod → ReplicaSet → Deployment. Return the Deployment name string. Return `"Could not resolve deployment"` if the chain breaks.

**`recall_past_cases(alert_type: str) -> str`**
Query SQLite: `SELECT diagnosis, action, outcome, confidence, created_at FROM incidents WHERE alert_type = ? ORDER BY id DESC LIMIT 3`. Format as a human-readable bullet list. Return `"No past cases."` if empty.

### MCP tools — write (healing actions)

Each write tool enforces three gates **in this order** before touching the cluster:

1. **Confidence gate:** `confidence < CONFIDENCE_THRESHOLD` (env var, default 0.75) → return `"Skipped: confidence {confidence:.2f} below threshold {threshold:.2f}"`
2. **Protected namespace gate** (not applicable to node actions): namespace in the protected set → return `"Skipped: namespace '{namespace}' is protected"`
3. **Dry-run gate:** `DRY_RUN` env var is `"true"` → log the intended action and return `"DRY_RUN: would execute {action} on {target}"`

Protected namespaces set: `{"kube-system", "kube-public", "kube-node-lease", "monitoring", "litmus", "kagent", "external-secrets", "cert-manager", "aws-load-balancer-controller", "local-path-storage"}`

**`restart_deployment(namespace: str, deployment: str, confidence: float, reason: str) -> str`**
After gates: patch the Deployment with annotation `kubectl.kubernetes.io/restartedAt = <UTC ISO timestamp>` via `patch_namespaced_deployment`. Return `"Restarted deployment/{deployment} in {namespace}"` on success or `"Failed: <error>"` on K8s API error.

**`scale_deployment(namespace: str, deployment: str, confidence: float, reason: str, alert_key: str = "") -> str`**
After gates: read current replica count. If `current >= MAX_REPLICAS` (env var, default 10), return `"Skipped: already at max replicas ({current})"`. Otherwise scale to `current + 1`. If `alert_key` is non-empty and not already in `_scale_state`, record `_scale_state[alert_key] = (namespace, deployment, current)` under `_scale_lock`. Return `"Scaled deployment/{deployment} from {current} to {current+1} replicas"`.

**`cordon_node(node_name: str, confidence: float, reason: str) -> str`**
Confidence gate only (no namespace check). Then HITL approval flow:
1. Generate `action_id = f"cordon-{node_name}-{uuid4().hex[:8]}"`
2. Register in `_approval_store` → get event
3. Build approval URL: `f"{WEBHOOK_BASE_URL}/approve/{action_id}"` (env var, default "")
4. Post Slack message: action requested, approval URL, auto-approves in N seconds
5. `event.wait(timeout=APPROVAL_TIMEOUT_SECONDS)` (env var, default 300)
6. Whether approved explicitly or timed out: cordon via `patch_node(name=node_name, body={"spec": {"unschedulable": True}})`
7. Cancel the approval entry if still pending (timeout case)
8. Return `"Cordoned node {node_name}"` or `"Failed: <error>"`

DRY_RUN check applies before the HITL flow.

**`drain_node(node_name: str, confidence: float, reason: str) -> str`**
Same HITL flow as `cordon_node`. After approval:
1. Cordon the node
2. List all pods on the node via `list_pod_for_all_namespaces(field_selector=spec.nodeName={node_name})`
3. Skip pods owned by DaemonSet or Node
4. Skip pods in protected namespaces
5. Evict remaining pods via `create_namespaced_pod_eviction`. HTTP 429 means PDB-blocked → add to retry list
6. Retry PDB-blocked pods with delays: 5s → 15s → 30s (three attempts total)
7. Return summary: `"Drained {node_name}: evicted {n} pods, skipped {m} (DaemonSet/protected/PDB-blocked)"`

### MCP tool — record (always the last tool Gemini calls)

**`record_outcome(alert_key: str, alert_name: str, severity: str, diagnosis: str, action: str, target: str, namespace: str, confidence: float, executed: bool, outcome: str, dry_run: bool) -> str`**

Does four things in sequence (each failure is logged, not raised):
1. Append one JSON line to the audit log at `_audit_path`. Format: all parameters + `"timestamp": UTC ISO string`
2. If `_slack_url` is set: POST a formatted Slack message with emoji (✅ if executed, ⛔ if not), alert key, action, confidence, diagnosis, outcome
3. If `_cw_client` is set: `put_metric_data` to namespace `KAgent/HealingEvents` with dimensions `Action` and `Executed`
4. Insert a row into the `incidents` SQLite table

Return `"Outcome recorded for {alert_key}"`.

### `scale_down_if_resolved(alert_key: str) -> None`

Called directly by `pipeline.run()` when an alert resolves (not a Gemini tool).

```
pop alert_key from _scale_state under _scale_lock
if not found: return
if DRY_RUN: log and return
patch_namespaced_deployment_scale to restore original_replicas
log success or error
```

### `call_tool(name: str, args: dict) -> str`

Module-level function. Dispatches to the matching tool implementation by name. Returns `"Unknown tool: {name}"` if not found. Wraps call in try/except, returns `"Tool error ({name}): {exc}"` on failure. This is called by `GeminiClient` when Gemini makes a tool call — no MCP transport involved.

### `ALL_DECLARATIONS`

A module-level list of all tool declarations in Gemini function-calling format (JSON Schema with lowercase types: `"object"`, `"string"`, `"number"`, `"boolean"`). Includes all read tools, all write tools, and `record_outcome`. Does **not** include `scale_down_if_resolved` (not a Gemini tool).

Each declaration is a dict with keys `name`, `description`, `parameters`. The `parameters` value is a JSON Schema object dict.

### Standalone MCP server entry point

```python
if __name__ == "__main__":
    if not _HAS_MCP:
        raise SystemExit("mcp package not installed")
    mcp.run()
```

FastMCP registrations (via `@mcp.tool()`) are only active in the `if mcp is not None:` block so that missing the `mcp` package does not break the in-process usage path.

---

## Specification: `agent/gemini.py`

### Constants

```python
DEFAULT_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
MAX_TURNS     = int(os.environ.get("GEMINI_MAX_TURNS", "8"))
VALID_ACTIONS = {"restart_deployment", "scale_deployment", "cordon_node", "drain_node", "notify_only", "no_action"}
```

### System prompt

```
You are an expert Kubernetes Site Reliability Engineer (SRE).

You have investigation tools that let you inspect a failing workload.
Use them to gather evidence, then act, then always call record_outcome last.

INVESTIGATION ORDER (adjust based on the alert type):
1. get_pod_events + get_pod_logs — fastest path to root cause
2. describe_pod — restart count, resource limits, current state
3. get_node_conditions — if pod is on a node that may be unhealthy
4. recall_past_cases — how similar alerts were resolved before
5. resolve_deployment — when you need the Deployment name

WHEN YOU HAVE ENOUGH EVIDENCE:
- If confidence >= 0.75: call the appropriate write tool (restart_deployment,
  scale_deployment, cordon_node, drain_node)
- If confidence < 0.70: do not call any write tool
- Always call record_outcome as your final tool call

STRICT RULES:
- deployment parameter in write tools MUST be a Deployment name, never a Pod name
- confidence < 0.70 → set action="notify_only" in record_outcome, skip write tools
- NEVER attempt to delete namespaces or cluster-scoped resources
- Prefer the least-disruptive action that addresses the root cause
- Call record_outcome EXACTLY ONCE as your last action
```

### `GeminiClient` class

```python
class GeminiClient:
    def __init__(self, api_key=None, model=None, max_retries=4, max_turns=MAX_TURNS)
    def diagnose(self, triage_result: dict) -> dict
```

**`diagnose()` implementation:**

If `_client` is None or `genai_types` is None: return the `NOTIFY_ONLY_FALLBACK` dict.

Build the initial user message:
```
Diagnose this Kubernetes alert and take appropriate action.

Alert:     {alert_name}
Namespace: {namespace}
Pod:       {pod}
Labels:    {json.dumps(labels)}

Investigate with tools, act if confident, then call record_outcome.
```

Build `GenerateContentConfig` with `system_instruction=SYSTEM_PROMPT`, `tools=[Tool(function_declarations=[FunctionDeclaration(**d) for d in mcp_server.ALL_DECLARATIONS])]`, `temperature=0.2`.

Run the tool-calling loop up to `max_turns` iterations:

Each iteration:
1. Call `_client.models.generate_content()` with retry on rate-limit (backoff: 1s, 2s, 4s, 8s up to `max_retries`)
2. If API call fails after all retries: return NOTIFY_ONLY_FALLBACK
3. If no candidates or empty parts: break loop
4. Append candidate content to `contents`
5. Extract all `function_call` parts from the response
6. If no function calls: break loop (Gemini returned text without acting — unexpected)
7. For each function call:
   - If name is `record_outcome`: capture args as `outcome_args`, add a `function_response` part with `{"status": "recorded"}`, **break the outer loop**
   - Otherwise: call `mcp_server.call_tool(name, args)`, add a `function_response` part with `{"result": result}`
8. If `record_outcome` was called: break
9. Append a new Content with all `function_response` parts and continue

After loop:
- If `outcome_args` was captured: return `_build_result(outcome_args)`
- Otherwise: return NOTIFY_ONLY_FALLBACK

**`_build_result(outcome_args: dict) -> dict`**

Normalise and return:
```python
{
    "action":     str(outcome_args.get("action", "notify_only")),
    "target":     str(outcome_args.get("target", "unknown")),
    "namespace":  str(outcome_args.get("namespace", "unknown")),
    "diagnosis":  str(outcome_args.get("diagnosis", "")),
    "confidence": float(outcome_args.get("confidence", 0.0)),
    "executed":   bool(outcome_args.get("executed", False)),
    "outcome":    str(outcome_args.get("outcome", "")),
    "dry_run":    bool(outcome_args.get("dry_run", False)),
}
```

**`NOTIFY_ONLY_FALLBACK`**

```python
{
    "action": "notify_only", "target": "unknown", "namespace": "unknown",
    "diagnosis": "Unable to diagnose.", "confidence": 0.0,
    "executed": False, "outcome": "Gemini unavailable or loop limit reached.",
    "dry_run": False,
}
```

---

## Specification: `agent/cost_guard.py`

Identical to the reference implementation:

```python
class CostGuard:
    def __init__(self, daily_limit: int | None = None)
    def check_and_increment(self) -> bool   # True = allowed, False = budget exhausted
    def remaining(self) -> int
    def used(self) -> int
```

- Thread-safe with `threading.Lock`
- Daily limit from `DAILY_REQUEST_LIMIT` env var, default 200
- Resets at midnight UTC by comparing `datetime.now(timezone.utc).strftime("%Y-%m-%d")` to stored day
- Logs a warning at 80% consumption (once per day)

---

## Specification: `agent/pipeline.py`

### Constants

```python
DEDUP_TTL_SECONDS = 300
SEVERITY_WEIGHTS  = {"critical": 3, "warning": 2, "info": 1}
```

### Module-level state

```python
_seen:      dict[str, float]  = {}   # alert_key → last_seen timestamp
_seen_lock: threading.Lock    = threading.Lock()
```

### `_alert_key(alert: dict) -> str`

```python
labels = alert.get("labels") or {}
return f"{labels.get('alertname','unknown')}:{labels.get('namespace','-')}:{labels.get('pod','-')}"
```

### `triage(alert: dict) -> dict | None`

1. Build `alert_key`
2. Build `severity = labels.get("severity", "info").lower()`
3. Under `_seen_lock`: prune expired entries, check if key is in `_seen` and within TTL → return None (duplicate)
4. Record `_seen[key] = now`
5. Return `{"alert_key": key, "alert_name": ..., "severity": severity, "severity_weight": SEVERITY_WEIGHTS.get(severity, 1), "namespace": ..., "pod": ..., "alert": alert}`

### `run(alert: dict, gemini_client, cost_guard) -> None`

```python
if alert.get("status") == "resolved":
    key = _alert_key(alert)
    mcp_server.scale_down_if_resolved(key)
    return

result = triage(alert)
if result is None:
    return

if not cost_guard.check_and_increment():
    logger.warning("Daily budget exhausted — skipping %s", result["alert_key"])
    return

gemini_client.diagnose(result)
```

Note: `diagnose()` returns a result dict but `run()` ignores the return value — `record_outcome` was already called inside the Gemini loop as a tool call. The audit happened inside Gemini.

---

## Specification: `agent/server.py`

### `WebhookServer` class

```python
class WebhookServer:
    def __init__(self, gemini_client, cost_guard, host="0.0.0.0", port=8000)
    def start(self) -> None    # blocks
    def stop(self) -> None
```

### HTTP routes

**`GET /health` and `GET /healthz` and `GET /readyz`**
Return `{"status": "ok", "version": "1.0.0"}` with status 200.

**`POST /webhook`**
1. Optional bearer-token auth: if `WEBHOOK_TOKEN` env var is set and non-empty, require `Authorization: Bearer {token}`. Return 401 if missing or wrong.
2. Parse JSON body. Return 400 on malformed JSON.
3. Extract `alerts` list from payload (or treat entire body as single alert).
4. For each alert dict: spawn a daemon thread calling `_safe_run(alert, gemini_client, cost_guard)`
5. Return `{"received": len(alerts)}` with status 200 immediately.

**`POST /approve/<action_id>`**
1. Call `mcp_server.approval_store.approve(action_id)`
2. If True: return `{"approved": action_id}` with 200
3. If False: return 404

**`_safe_run(alert, gemini_client, cost_guard)`**
Wraps `pipeline.run(alert, gemini_client, cost_guard)` in try/except. Logs exception, never re-raises. A single bad alert must never crash the server.

---

## Specification: `agent/main.py`

### Startup sequence

```python
def main() -> int:
    _configure_logging()
    _load_secrets_from_aws()       # fetch GEMINI_API_KEY + SLACK_WEBHOOK_URL from Secrets Manager if in-cluster
    _init_mcp_server()             # call mcp_server.init() with all deps
    metrics = _build_metrics()     # register Prometheus counters/gauges/histograms
    gemini = GeminiClient()
    cost_guard = CostGuard()
    start_http_server(int(os.environ.get("METRICS_PORT", "8001")))
    server = WebhookServer(gemini, cost_guard, port=int(os.environ.get("WEBHOOK_PORT", "8000")))
    try:
        server.start()
    except KeyboardInterrupt:
        server.stop()
    return 0
```

### `_init_mcp_server()`

```python
mcp_server.init(
    core_api    = k8s_client.CoreV1Api(),   # after loading in-cluster or local kubeconfig
    apps_api    = k8s_client.AppsV1Api(),
    db_path     = os.environ.get("MEMORY_DB_PATH", "/tmp/kagent-memory.db"),
    audit_path  = os.environ.get("AUDIT_LOG_PATH", "/tmp/kagent-audit.jsonl"),
    slack_url   = os.environ.get("SLACK_WEBHOOK_URL", ""),
    aws_region  = os.environ.get("AWS_REGION", "ap-south-1"),
)
```

Try `load_incluster_config()` first, fall back to `load_kube_config()`. If both fail, log a warning and continue — mcp_server tools will return "Unavailable" strings but the server will still run.

### Prometheus metrics

Register these metrics (labels where noted):

```
kagent_alerts_total          Counter   labels: [severity]
kagent_gemini_calls_total    Counter
kagent_actions_total         Counter   labels: [action, executed]
kagent_healing_seconds       Histogram
kagent_last_confidence       Gauge
kagent_requests_remaining    Gauge     set_function(lambda: float(cost_guard.remaining()))
```

These are passed to `WebhookServer` which increments them inside `_safe_run` after `pipeline.run()` returns. Specifically: increment `kagent_gemini_calls_total` before calling `gemini.diagnose()`; use the returned result dict for the other metrics.

### AWS Secrets Manager loading

Only runs if `KUBERNETES_SERVICE_HOST` env var is set. Fetches:
- Secret ID from `GEMINI_API_KEY_SECRET` env var (default `kagent/gemini-api-key`) → sets `GEMINI_API_KEY`
- Secret ID from `SLACK_WEBHOOK_SECRET` env var (default `kagent/slack-webhook`) → sets `SLACK_WEBHOOK_URL`

Skip each if the env var is already set. Log errors, never raise.

---

## Specification: `agent/requirements.txt`

```
google-genai>=1.0.0
kubernetes>=29.0.0
python-dotenv>=1.0.0
prometheus-client>=0.20.0
requests>=2.31.0
boto3>=1.34.0
mcp>=1.0.0
```

---

## Specification: Tests

### `agent/tests/conftest.py`

Add the project root to `sys.path` so imports work without installation.

### `agent/tests/test_mcp_server.py`

Test the MCP server tools with mocked Kubernetes clients. Use `pytest` fixtures.

**Setup fixture:** Create a mock `CoreV1Api` and `AppsV1Api`. Call `mcp_server.init()` with those mocks plus a temporary SQLite path and empty strings for slack/audit.

**Read tool tests:**
- `test_get_pod_logs_returns_previous_first` — mock `read_namespaced_pod_log` to return "PREV" for `previous=True`, verify result contains "PREV"
- `test_get_pod_logs_falls_back_to_current` — first call raises, second returns "CURR", verify result contains "CURR"
- `test_get_pod_events_sorted_descending` — mock two events with different timestamps, verify newer appears first in JSON output
- `test_describe_pod_returns_phase_and_node` — mock pod with phase="Running", node_name="ip-1-2-3-4", verify both appear in result
- `test_get_node_conditions_returns_json` — mock node with one condition, verify JSON output
- `test_resolve_deployment_walks_owner_refs` — mock pod ownerRef→ReplicaSet ownerRef→Deployment, verify deployment name returned
- `test_recall_past_cases_returns_no_past_cases_when_empty` — no rows in DB, verify `"No past cases."` returned
- `test_recall_past_cases_returns_matching_rows` — insert 2 rows, verify both appear in recall output

**Write tool tests:**
- `test_restart_deployment_low_confidence_skipped` — confidence=0.5, verify result contains "below threshold"
- `test_restart_deployment_protected_namespace_skipped` — namespace="kube-system", verify result contains "protected"
- `test_restart_deployment_dry_run_skips_patch` — set `DRY_RUN=true`, verify `patch_namespaced_deployment` not called
- `test_restart_deployment_patches_annotation` — live mode, verify `patch_namespaced_deployment` called with `restartedAt` annotation
- `test_scale_deployment_increments_by_one` — current replicas=3, verify scale called with 4
- `test_scale_deployment_respects_max` — current=max, verify scale not called, result mentions "max replicas"
- `test_scale_deployment_records_original_count` — scale up with alert_key, verify `_scale_state` contains original count

**record_outcome tests:**
- `test_record_outcome_writes_jsonl` — call record_outcome, read audit file, verify one JSON line written
- `test_record_outcome_stores_in_sqlite` — call record_outcome, query DB directly, verify row inserted
- `test_record_outcome_posts_to_slack` — set slack url, mock `requests.post`, verify it was called

**ApprovalStore tests:**
- `test_approve_sets_event`
- `test_unknown_id_returns_false`
- `test_cancel_removes_entry`
- `test_approve_twice_returns_false`

**scale_down_if_resolved tests:**
- `test_scale_down_restores_original_replicas` — pre-populate `_scale_state`, call `scale_down_if_resolved`, verify patch called with original count
- `test_scale_down_noop_when_not_tracked`
- `test_scale_down_dry_run_skips_patch`

### `agent/tests/test_gemini.py`

Test the GeminiClient tool-calling loop with mocked Gemini SDK.

**Helper builders:**
- `_fc_part(name, args)` — fake a Part with a function_call
- `_text_part(text)` — fake a Part with text and no function_call
- `_response(*parts)` — fake a response with one candidate containing the given parts
- `_triage(alertname, ns, pod)` — minimal triage result dict

**Tests:**
- `test_record_outcome_call_concludes_loop` — mock Gemini to return `record_outcome` tool call on first turn; verify result dict returned, `call_tool` not called (record_outcome is captured, not dispatched)
- `test_investigation_tool_then_record_outcome` — turn 1: `get_pod_logs` call; turn 2: `record_outcome` call; verify `call_tool` called once for `get_pod_logs`
- `test_multiple_investigation_tools` — two investigation tools, then record_outcome; verify Gemini called 3 times
- `test_max_turns_returns_fallback` — always return investigation tool, never record_outcome; verify fallback returned after max_turns
- `test_api_error_returns_fallback` — side_effect=RuntimeError; verify fallback returned
- `test_empty_candidates_returns_fallback`
- `test_text_response_without_tool_returns_fallback` — Gemini returns text only; verify fallback
- `test_rate_limit_retries_then_succeeds` — first N calls raise "429 RESOURCE_EXHAUSTED", Nth+1 succeeds; verify sleep called, final result correct
- `test_no_client_returns_fallback` — `_client = None`; verify fallback immediately returned

### `agent/tests/test_pipeline.py`

- `test_first_alert_passes_through` — new alert, verify `gemini_client.diagnose` called
- `test_duplicate_within_ttl_dropped` — same alert twice within 300s, verify `diagnose` called only once
- `test_duplicate_after_ttl_passes` — same alert, advance time past TTL, verify `diagnose` called twice
- `test_resolved_alert_calls_scale_down_not_diagnose` — status="resolved", verify `scale_down_if_resolved` called, `diagnose` not called
- `test_budget_exhausted_skips_diagnose` — cost_guard returns False, verify `diagnose` not called
- `test_severity_weight_attached` — critical alert, verify triage result has `severity_weight=3`
- `test_different_pods_same_alert_not_duplicates` — same alertname different pod, both pass through

### `agent/tests/test_server.py`

Use `ThreadingHTTPServer` bound to port 0 for real HTTP testing (same pattern as existing tests).

- `test_health_returns_ok` — GET /health returns 200 with `{"status": "ok"}`
- `test_webhook_fires_pipeline` — POST /webhook with one alert; give thread 1s to run; verify `pipeline.run` was called
- `test_webhook_returns_immediately` — POST /webhook; verify 200 returned before pipeline finishes
- `test_malformed_json_returns_400`
- `test_auth_wrong_token_returns_401` — monkeypatch `_WEBHOOK_TOKEN = "correct"`, send "Bearer wrong"
- `test_auth_correct_token_returns_200`
- `test_no_auth_when_token_unset` — no token configured, no auth header, verify 200
- `test_approve_endpoint_sets_event` — register an action in approval_store, POST /approve/<id>, verify event set
- `test_approve_unknown_id_returns_404`

---

## Specification: Helm chart changes

### `helm/kagent-healer/templates/configmap.yaml`

Add one entry:
```yaml
GEMINI_MAX_TURNS: {{ .Values.agent.geminiMaxTurns | default "8" | quote }}
```

Keep all existing entries unchanged.

### `helm/kagent-healer/values.yaml`

Add one field under `agent:`:
```yaml
  geminiMaxTurns: "8"
```

Keep all existing fields unchanged.

---

## Specification: `.env.example`

Add:
```
GEMINI_MAX_TURNS=8
```

Keep all existing entries.

---

## Specification: Diagrams

### `diagrams/low-level-flow.mmd`

Rewrite as a Mermaid sequence diagram showing the new MCP tool-calling flow. Must include these participants and interactions:

- Alertmanager → WebhookServer: POST /webhook
- WebhookServer → pipeline.run(): spawn thread
- pipeline: triage (dedup check)
- pipeline → GeminiClient: diagnose(triage_result)
- GeminiClient → Gemini API: generate_content (with tools)
- Gemini → MCPServer: get_pod_events (tool call)
- Gemini → MCPServer: get_pod_logs (tool call)
- Gemini → MCPServer: restart_deployment (tool call, with safety gates inline note)
- Gemini → MCPServer: record_outcome (tool call, final)
- MCPServer → Kubernetes API: actual API calls
- MCPServer → SQLite: store incident
- MCPServer → Slack: notify
- MCPServer → CloudWatch: metric
- Resolved alert path: WebhookServer → pipeline → mcp_server.scale_down_if_resolved
- HITL path: cordon/drain → ApprovalStore.register → Slack message → wait for POST /approve/<id>

Use `autonumber` and `alt/else` blocks for: duplicate alert drop, resolved vs firing, HITL approval vs timeout, dry-run.

### `diagrams/high-level-flow.mmd`

Keep the same Mermaid flowchart LR structure and styling. Update the `AG` node label and arrows to reflect that Gemini drives tool calls rather than a fixed pipeline. The key change: remove any reference to separate pipeline stages in the agent box.

---

## Specification: README changes

Keep all section headers, formatting, badge styling, and overall document structure. Update only the following content:

**Architecture diagram (inline Mermaid in README):** Update to match the new `high-level-flow.mmd`.

**Tech stack table:** Remove any row referencing ContextBuilder, Remediator, or Agent pipeline classes. The agent row should describe: "MCP server + Gemini tool-calling loop".

**How it works / Pipeline section:** Replace the 4-agent pipeline description with the new 3-step flow: triage → Gemini tool-calling investigation → record_outcome. Emphasise that Gemini drives investigation and action rather than receiving a pre-built context.

**Healing actions table:** Keep all rows and columns. Update the "How" column to note that safety gates (confidence, protected namespace, dry-run) are enforced inside each MCP write tool.

**Configuration reference table:** Add `GEMINI_MAX_TURNS` row. Keep all existing rows.

**Day-2 operations / HITL section:** Keep content, verify the `/approve/<id>` URL format is still accurate.

---

## Environment variables reference

Complete list with defaults:

| Variable | Default | Description |
|---|---|---|
| `GEMINI_API_KEY` | — | Gemini API key (required) |
| `GEMINI_MODEL` | `gemini-2.5-flash` | Model name |
| `GEMINI_MAX_TURNS` | `8` | Max tool-calling turns per investigation |
| `CONFIDENCE_THRESHOLD` | `0.75` | Minimum confidence for write tools to execute |
| `MAX_REPLICAS` | `10` | Scale-up ceiling |
| `DRY_RUN` | `true` | Skip real K8s mutations when true |
| `DAILY_REQUEST_LIMIT` | `200` | Max Gemini calls per UTC day |
| `WEBHOOK_PORT` | `8000` | Webhook server port |
| `METRICS_PORT` | `8001` | Prometheus metrics port |
| `WEBHOOK_TOKEN` | `""` | Bearer token for /webhook auth (optional) |
| `WEBHOOK_BASE_URL` | `""` | External base URL for /approve/<id> links in Slack |
| `APPROVAL_TIMEOUT_SECONDS` | `300` | Auto-approve HITL after this many seconds |
| `MEMORY_DB_PATH` | `/tmp/kagent-memory.db` | SQLite database path |
| `AUDIT_LOG_PATH` | `/tmp/kagent-audit.jsonl` | Audit log path |
| `SLACK_WEBHOOK_URL` | `""` | Slack incoming webhook URL |
| `AWS_REGION` | `ap-south-1` | AWS region |
| `GEMINI_API_KEY_SECRET` | `kagent/gemini-api-key` | Secrets Manager secret ID |
| `SLACK_WEBHOOK_SECRET` | `kagent/slack-webhook` | Secrets Manager secret ID |
| `LOG_LEVEL` | `INFO` | Python logging level |

---

## Acceptance criteria

The implementation is correct when:

1. `python -m pytest agent/tests/ -v` passes all tests with no failures
2. `mypy agent/ --ignore-missing-imports` exits 0
3. `ruff check agent/` exits 0
4. `black --check agent/` exits 0
5. `helm lint helm/kagent-healer/ --set image.repository=placeholder` exits 0
6. `python -m agent.mcp_server` starts without error (FastMCP server running)
7. The five source files (`mcp_server.py`, `gemini.py`, `pipeline.py`, `server.py`, `main.py`) contain no imports of each other except: `pipeline.py` imports `mcp_server`; `gemini.py` imports `mcp_server`; `server.py` imports `pipeline`; `main.py` imports all four
8. There are no classes named `ContextBuilder`, `Remediator`, `TriageAgent`, `DiagnosisAgent`, `RemediationAgent`, or `AuditAgent` anywhere in `agent/`
9. All safety gates (confidence, protected namespace, dry-run) are implemented inside the write tool functions in `mcp_server.py` — not in `pipeline.py`, `gemini.py`, or `server.py`
10. `record_outcome` is called as a Gemini tool call (inside the `gemini.py` loop), not called directly by `pipeline.py`
