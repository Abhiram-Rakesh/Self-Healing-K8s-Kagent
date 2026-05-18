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
| `mypy` | Static type checking (`--ignore-missing-imports`) |
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
3. If the action is high-impact, add its name to `REQUIRES_APPROVAL` in
   `agent/agents/remediation_agent.py`.
4. Add a Prometheus alert rule in `k8s/monitoring/alert-rules.yaml` that
   can trigger the new action.
5. Add unit tests in `agent/tests/test_remediator.py`.
6. Update the healing actions table in `README.md`.

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
- [ ] High-impact actions are listed in `REQUIRES_APPROVAL`

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
