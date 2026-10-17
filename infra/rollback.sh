#!/usr/bin/env bash
set -euo pipefail
source "$(dirname "$0")/common.sh"
if [[ "${1:-}" == '--apply' ]]; then APPLY=1; shift; fi
REVISION="${1:-}"
DIGEST="${2:-}"
[[ "$REVISION" =~ ^evidencedesk-web-[a-z0-9-]+$ && "$DIGEST" =~ ^sha256:[a-f0-9]{64}$ ]] || { printf 'Usage: %s [--apply] VERIFIED_PRIOR_WEB_REVISION sha256:PRIOR_WORKER_IMAGE\n' "$0" >&2; exit 2; }
require_cli
require_approval_notice
run gcloud run services update-traffic "$WEB_SERVICE" --to-revisions="$REVISION=100" --region="$REGION" --project="$PROJECT"
run gcloud run jobs update "$WORKER_JOB" --image="$IMAGE_BASE@$DIGEST" --region="$REGION" --project="$PROJECT"
printf 'Rollback changes code traffic and future worker executions, not stored reviews, migrations, or already running executions. Verify current job executions separately.\n'
