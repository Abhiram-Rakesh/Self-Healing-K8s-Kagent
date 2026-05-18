---
name: Bug report
about: Something is broken — help us reproduce and fix it.
title: "[BUG] "
labels: bug
assignees: ""
---

## Describe the bug
A clear and concise description of what is broken.

## Reproduction steps
1. ...
2. ...
3. ...

## Expected behavior
What you expected to happen.

## Actual behavior
What actually happened. Paste relevant agent logs:
```
kubectl logs -n kagent -l app.kubernetes.io/name=kagent-healer --tail=200
```

## Environment
- Repo version / commit:
- Kubernetes version (`kubectl version --short`):
- Terraform version (`terraform --version`):
- Cloud / region:
- Helm chart version:

## Additional context
Screenshots, related issues, anything else.
