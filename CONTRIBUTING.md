# Contributing

Thank you for taking the time to contribute. This guide covers everything you
need to get from a fresh clone to an open PR.

## Getting started

```bash
git clone https://github.com/YOUR_USERNAME/self-healing-k8s-kagent.git
cd self-healing-k8s-kagent

# Install Python runtime + dev tools
make install

# Verify everything works
make lint
make test
```

## Development workflow

1. **Fork** the repository and create a branch from `main`.
2. Make your changes — keep commits focused (one logical change per commit).
3. Run `make lint` and `make test` locally — CI will reject PRs where either fails.
4. Open a pull request against `main` using the PR template.

## Code style

| Tool | What it checks |
|------|----------------|
| `ruff` | Python linting (E/F/W/I rules) |
| `black` | Python formatting (88-char line length) |
| `mypy` | Static type checking (`--ignore-missing-imports`) — **failures block CI** |
| `hadolint` | Dockerfile best practices |
| `shellcheck` | Shell script correctness |
| `terraform fmt` | HCL formatting |
| `helm lint` | Helm chart validity |

Run all of them at once: `make lint`.

## Running tests

```bash
make test
# or directly:
pytest agent/tests/ -v --cov=agent --cov-report=term-missing
```

Tests must not require a live Kubernetes cluster or a real Gemini API key —
mock everything at the boundary.

## Adding a new healing action

1. Implement the action method in `agent/remediator.py` (`_my_action`).
2. Wire it into `Remediator.execute()` under the action name string.
3. If the action is high-impact (destructive or cluster-wide), add its name to
   `REQUIRES_APPROVAL` in `agent/agents/remediation_agent.py` — the
   `ApprovalStore` flow will handle the Slack notification and
   `POST /approve/<id>` wait automatically.
4. If the action scales resources **up**, store the original count in
   `self._scale_state` (keyed by `plan.get("alert_key")`) so
   `scale_down_if_tracked()` can reverse it when the alert resolves. See the
   existing `scale_up` path in `Remediator.execute()` as the pattern to follow.
5. The context dict passed to Gemini now includes `deployment_name` (resolved
   from the pod's ownerReferences). Reference it in your system prompt
   additions rather than relying on Gemini to infer the deployment from the pod
   name.
6. Add a Prometheus alert rule in `k8s/monitoring/alert-rules.yaml` that
   can trigger the new action.
7. Add unit tests in `agent/tests/test_remediator.py`.
8. Update the healing actions table in `README.md`.

## Adding a new alert rule

1. Edit `k8s/monitoring/alert-rules.yaml`.
2. Set `kagent: "true"` on the alert label so Alertmanager routes it to the
   webhook.
3. Document it in the "Custom alert rules" section of `README.md`.
4. Test it by applying a test workload from `k8s/test-workloads/`.

## Terraform changes

- Run `terraform fmt -recursive terraform/` before committing.
- Add any new variable to `terraform/variables.tf` with a `description` and
  safe `default`.
- Update `terraform/terraform.tfvars.example` with a commented example value.
- The CI workflow runs `terraform plan` on every PR — check the plan comment
  before merging.

## Safety checklist for remediator / alert-rule changes

- [ ] `PROTECTED_NAMESPACES` still includes `kube-system`, `kagent`, `monitoring`
- [ ] No new action executes without passing the confidence gate
- [ ] `DRY_RUN=true` remains the default in `helm/kagent-healer/values.yaml`
- [ ] High-impact actions are listed in `REQUIRES_APPROVAL` (triggers the `ApprovalStore` HITL flow)
- [ ] Scale-modifying actions store their pre-change state in `_scale_state` and are reversed by `scale_down_if_tracked()` on alert resolution
- [ ] `WEBHOOK_TOKEN` is never hardcoded — leave `agent.webhookToken` empty in `values.yaml` and inject via `extraEnv` referencing a K8s Secret in production

## Helm chart changes

When modifying the Helm chart:

- **New env vars** belong in `helm/kagent-healer/templates/configmap.yaml` (non-sensitive) or injected via `extraEnv` referencing a K8s Secret (sensitive values like tokens or API keys). Never put secret values directly in `values.yaml`.
- **Persistence** is controlled by `persistence.enabled`. When `true`, the chart provisions a PVC and mounts it at `/data`; the configmap automatically overrides `MEMORY_DB_PATH` and `AUDIT_LOG_PATH` to `/data/...`. Dev default is `false` (emptyDir at `/tmp`); production default (`values-prod.yaml`) is `true`.
- **New volumes** must be mounted explicitly in `deployment.yaml` — the root filesystem is read-only (`readOnlyRootFilesystem: true`), so any path the agent writes to needs either an emptyDir or PVC mount.
- Run `helm lint helm/kagent-healer/ --set image.repository=placeholder` before pushing.

## Commit messages

Use the [Conventional Commits](https://www.conventionalcommits.org/) style:

```
feat: add drain_node healing action
fix: handle 429 retry in gemini_client
chore: bump python:3.11-slim base image
docs: update README with Loki install step
```

## Releasing

Maintainers cut releases by pushing a semver tag:

```bash
git tag v1.2.3
git push origin v1.2.3
```

CI builds and pushes the versioned image to ECR and creates a GitHub Release
automatically.
