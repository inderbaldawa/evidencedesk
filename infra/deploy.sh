#!/usr/bin/env bash
set -euo pipefail
source "$(dirname "$0")/common.sh"
if [[ "${1:-}" == '--apply' ]]; then APPLY=1; shift; fi
DIGEST="${1:-}"
[[ "$DIGEST" =~ ^sha256:[a-f0-9]{64}$ ]] || { printf 'Usage: %s [--apply] sha256:IMAGE_DIGEST\n' "$0" >&2; exit 2; }
require_cli
require_approval_notice
IMAGE="$IMAGE_BASE@$DIGEST"
if [[ "$APPLY" == 1 ]]; then
  [[ -f "$INFRA_DIR/.local/web-env.json" && -f "$INFRA_DIR/.local/worker-env.json" ]] || { printf 'Run render-env.py with the dedicated Firebase Web config first.\n' >&2; exit 1; }
  mkdir -p "$INFRA_DIR/.local"
  # Save the entire previous definition for operator-selected rollback; no guessed revision.
  if gcloud run services describe "$WEB_SERVICE" --region="$REGION" --project="$PROJECT" --format=json > "$INFRA_DIR/.local/pre-deploy-service.json" 2> "$INFRA_DIR/.local/pre-deploy-service-error.txt"; then
    printf 'Previous service snapshot saved in infra/.local/pre-deploy-service.json.\n'
  elif ! grep -Eqi 'not found|NOT_FOUND|does not exist' "$INFRA_DIR/.local/pre-deploy-service-error.txt"; then
    cat "$INFRA_DIR/.local/pre-deploy-service-error.txt" >&2; exit 1
  fi
fi
run gcloud run jobs deploy "$WORKER_JOB" --image="$IMAGE" --service-account="$WORKER_SA" --region="$REGION" --tasks=1 --parallelism=1 --cpu=1 --memory=1Gi --max-retries=1 --task-timeout=900s --command=python --args=-m,app.backend.worker --env-vars-file="$INFRA_DIR/.local/worker-env.json" --project="$PROJECT"
run gcloud run jobs add-iam-policy-binding "$WORKER_JOB" --region="$REGION" --member="serviceAccount:$WEB_SA" --role=roles/run.jobsExecutorWithOverrides --project="$PROJECT"
run gcloud run deploy "$WEB_SERVICE" --image="$IMAGE" --service-account="$WEB_SA" --region="$REGION" --cpu=1 --memory=512Mi --min=0 --max=2 --max-instances=2 --concurrency=8 --timeout=60s --port=8080 --cpu-throttling --no-cpu-boost --ingress=all --allow-unauthenticated --env-vars-file="$INFRA_DIR/.local/web-env.json" --project="$PROJECT"
run gcloud run services describe "$WEB_SERVICE" --region="$REGION" --format='value(status.url,status.latestReadyRevisionName)' --project="$PROJECT"
printf 'Deployment does not seed data or execute a model request. Verify Firebase, ledger, private storage, and source sample before judging.\n'
