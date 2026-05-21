#!/bin/bash
# teardown.sh — destroys everything in the correct order.
# Order matters: PVCs first (lets CSI driver clean EBS volumes), then Helm
# releases (cleans up AWS LBs), then namespaces, then ENI wait, then straggler
# ELBs, then Terraform, then orphaned EBS volumes, then the S3 state bucket.
set -euo pipefail

RED=$'\033[0;31m'
GREEN=$'\033[0;32m'
YELLOW=$'\033[1;33m'
CYAN=$'\033[0;36m'
NC=$'\033[0m'

log()  { printf "%s[teardown]%s %s\n" "$CYAN" "$NC" "$*"; }
ok()   { printf "%s[   ok   ]%s %s\n" "$GREEN" "$NC" "$*"; }
warn() { printf "%s[  warn  ]%s %s\n" "$YELLOW" "$NC" "$*"; }
die()  { printf "%s[  err   ]%s %s\n" "$RED" "$NC" "$*" >&2; exit 1; }

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TF_DIR="${TF_DIR:-$REPO_ROOT/terraform}"
AWS_REGION="${AWS_REGION:-ap-south-1}"
CONFIRM_PHRASE="yes I want to destroy everything"

read -r -p "Type exactly: \"$CONFIRM_PHRASE\" to proceed > " RESPONSE
[[ "$RESPONSE" == "$CONFIRM_PHRASE" ]] || die "Confirmation phrase did not match — aborting"

# ---------------------------------------------------------------------------
# 1) Delete all PVCs so the EBS CSI driver removes the backing EBS volumes
#    before the cluster is torn down (avoids orphaned volumes).
# ---------------------------------------------------------------------------
log "1) Deleting all PVCs (lets EBS CSI driver clean up volumes)"
for ns in $(kubectl get ns -o jsonpath='{.items[*].metadata.name}' 2>/dev/null || true); do
  PVC_COUNT=$(kubectl get pvc -n "$ns" --no-headers 2>/dev/null | wc -l)
  if (( PVC_COUNT > 0 )); then
    log "  deleting $PVC_COUNT PVC(s) in $ns"
    kubectl delete pvc --all -n "$ns" --timeout=120s || warn "  PVC delete timed out in $ns"
  fi
done

# ---------------------------------------------------------------------------
# 2) Uninstall Helm releases (triggers controller cleanup of AWS LBs/TGs)
# ---------------------------------------------------------------------------
log "2) Uninstalling Helm releases"
for ns_release in \
    "default kagent-healer" \
    "kagent kagent" \
    "kagent kagent-crds" \
    "monitoring loki" \
    "monitoring monitoring" \
    "litmus litmus"; do
  ns="${ns_release% *}"; release="${ns_release#* }"
  if helm -n "$ns" status "$release" >/dev/null 2>&1; then
    log "  helm uninstall $release -n $ns"
    helm -n "$ns" uninstall "$release" --wait --timeout 5m || warn "  uninstall of $release failed"
  fi
done

# ---------------------------------------------------------------------------
# 3) Delete kagent-healer workloads from default namespace + named namespaces
# ---------------------------------------------------------------------------
log "3) Deleting kagent-healer workloads from default namespace"
kubectl delete deploy,svc,sa,rolebinding,role \
  -n default -l app.kubernetes.io/name=kagent-healer --ignore-not-found || true
kubectl delete deploy,svc,sa,rolebinding,role \
  -n default -l app.kubernetes.io/part-of=kagent-healer --ignore-not-found || true

log "4) Deleting namespaces"
for ns in kagent monitoring litmus; do
  if kubectl get ns "$ns" >/dev/null 2>&1; then
    log "  kubectl delete ns $ns"
    kubectl delete ns "$ns" --wait=true --timeout=5m || warn "  ns/$ns delete timed out"
  fi
done

# ---------------------------------------------------------------------------
# 5) Wait for AWS to detach and remove ENIs from the VPC's subnets
# ---------------------------------------------------------------------------
log "5) Waiting 60s for AWS to detach ENIs"
sleep 60

# ---------------------------------------------------------------------------
# 6) Force-delete any remaining ELBs in the VPC (Kubernetes controllers sometimes miss these)
# ---------------------------------------------------------------------------
VPC_ID="$(terraform -chdir="$TF_DIR" output -raw vpc_id 2>/dev/null || true)"
if [[ -n "$VPC_ID" ]]; then
  log "6) Cleaning leftover ELBs/NLBs in VPC $VPC_ID"
  LB_ARNS="$(aws elbv2 describe-load-balancers --region "$AWS_REGION" \
              --query "LoadBalancers[?VpcId=='$VPC_ID'].LoadBalancerArn" --output text || true)"
  for arn in $LB_ARNS; do
    log "  deleting $arn"
    aws elbv2 delete-load-balancer --region "$AWS_REGION" --load-balancer-arn "$arn" || warn "  delete $arn failed"
  done
  CLB_NAMES="$(aws elb describe-load-balancers --region "$AWS_REGION" \
                --query "LoadBalancerDescriptions[?VPCId=='$VPC_ID'].LoadBalancerName" --output text || true)"
  for name in $CLB_NAMES; do
    log "  deleting classic ELB $name"
    aws elb delete-load-balancer --region "$AWS_REGION" --load-balancer-name "$name" || warn "  delete $name failed"
  done
  if [[ -n "$LB_ARNS$CLB_NAMES" ]]; then
    log "  sleeping 60s for ENI propagation"
    sleep 60
  fi
else
  warn "Could not read vpc_id from terraform output — skipping ELB cleanup"
fi

# ---------------------------------------------------------------------------
# 7) terraform destroy
# ---------------------------------------------------------------------------
log "7) terraform destroy"
terraform -chdir="$TF_DIR" destroy -auto-approve || die "terraform destroy failed — see the README troubleshooting section"

# ---------------------------------------------------------------------------
# 8) Delete any orphaned EBS volumes (dynamic PVCs that CSI driver missed)
# ---------------------------------------------------------------------------
log "8) Cleaning up orphaned EBS volumes"
CLUSTER_NAME="$(terraform -chdir="$TF_DIR" output -raw cluster_name 2>/dev/null || true)"
if [[ -n "$CLUSTER_NAME" ]]; then
  ORPHAN_VOLS="$(aws ec2 describe-volumes --region "$AWS_REGION" \
    --filters "Name=status,Values=available" \
               "Name=tag:kubernetes.io/cluster/${CLUSTER_NAME},Values=owned" \
    --query 'Volumes[*].VolumeId' --output text || true)"
  # Also catch volumes tagged by the dynamic PVC name pattern
  ORPHAN_VOLS_NAME="$(aws ec2 describe-volumes --region "$AWS_REGION" \
    --filters "Name=status,Values=available" \
    --query "Volumes[?starts_with(Tags[?Key=='Name'].Value|[0], '${CLUSTER_NAME}-dynamic-pvc')].VolumeId" \
    --output text 2>/dev/null || true)"
  for vol in $ORPHAN_VOLS $ORPHAN_VOLS_NAME; do
    log "  deleting orphaned volume $vol"
    aws ec2 delete-volume --region "$AWS_REGION" --volume-id "$vol" || warn "  delete $vol failed"
  done
else
  # Fallback: find available volumes tagged with the project
  ORPHAN_VOLS="$(aws ec2 describe-volumes --region "$AWS_REGION" \
    --filters "Name=status,Values=available" \
               "Name=tag:Project,Values=kagent-healer" \
    --query 'Volumes[*].VolumeId' --output text || true)"
  for vol in $ORPHAN_VOLS; do
    log "  deleting orphaned volume $vol"
    aws ec2 delete-volume --region "$AWS_REGION" --volume-id "$vol" || warn "  delete $vol failed"
  done
fi

# ---------------------------------------------------------------------------
# 9) Delete the S3 Terraform state bucket (versioned — must purge all versions first)
# ---------------------------------------------------------------------------
STATE_BUCKET="$(grep 'state_bucket' "$TF_DIR/terraform.tfvars" 2>/dev/null \
  | awk -F'"' '{print $2}' || true)"
if [[ -n "$STATE_BUCKET" ]] && aws s3api head-bucket --bucket "$STATE_BUCKET" --region "$AWS_REGION" 2>/dev/null; then
  log "9) Deleting S3 state bucket: $STATE_BUCKET"

  # Delete all object versions
  VERSIONS="$(aws s3api list-object-versions --region "$AWS_REGION" \
    --bucket "$STATE_BUCKET" \
    --query '{Objects: Versions[].{Key:Key,VersionId:VersionId}}' \
    --output json 2>/dev/null || true)"
  if [[ "$VERSIONS" != "null" && "$VERSIONS" != '{"Objects": null}' && -n "$VERSIONS" ]]; then
    aws s3api delete-objects --region "$AWS_REGION" --bucket "$STATE_BUCKET" --delete "$VERSIONS" >/dev/null || true
  fi

  # Delete all delete markers
  MARKERS="$(aws s3api list-object-versions --region "$AWS_REGION" \
    --bucket "$STATE_BUCKET" \
    --query '{Objects: DeleteMarkers[].{Key:Key,VersionId:VersionId}}' \
    --output json 2>/dev/null || true)"
  if [[ "$MARKERS" != "null" && "$MARKERS" != '{"Objects": null}' && -n "$MARKERS" ]]; then
    aws s3api delete-objects --region "$AWS_REGION" --bucket "$STATE_BUCKET" --delete "$MARKERS" >/dev/null || true
  fi

  aws s3 rb "s3://$STATE_BUCKET" --region "$AWS_REGION" && ok "State bucket deleted" \
    || warn "Could not delete state bucket — check for remaining objects"
else
  warn "State bucket not found or already deleted — skipping"
fi

ok "Teardown complete. All AWS resources removed."
