## Summary
<!-- 1–3 bullets describing what this PR changes and why. -->

## Type of change
- [ ] Bug fix
- [ ] New feature (new healing action / alert rule / integration)
- [ ] Refactor
- [ ] Documentation
- [ ] Infrastructure (Terraform / Helm / CI)

## Test plan
- [ ] `make lint` passes locally
- [ ] `make test` passes locally with no new coverage regressions
- [ ] `helm lint helm/kagent-healer/` passes
- [ ] `terraform fmt -check -recursive terraform/` passes
- [ ] Manually tested on a kind/minikube/EKS cluster (describe the scenario):

## Safety review (for changes to mcp_server.py, agent.yaml, or alert-rules.yaml)
- [ ] PROTECTED_NAMESPACES still includes `kube-system`, `kagent`, `monitoring`, etc.
- [ ] No new write tool runs without a confidence gate
- [ ] New tool is listed in `k8s/kagent/agent.yaml` toolNames and system prompt is updated
- [ ] DRY_RUN=true remains the default in `helm/kagent-healer/values.yaml`

## Screenshots / logs (optional)
