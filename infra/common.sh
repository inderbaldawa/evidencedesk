#!/usr/bin/env bash
set -euo pipefail
INFRA_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$INFRA_DIR/.." && pwd)"
PROJECT="${GOOGLE_CLOUD_PROJECT:?Set GOOGLE_CLOUD_PROJECT to your own project ID}"
PROJECT_NUMBER="${GOOGLE_CLOUD_PROJECT_NUMBER:-}"
REGION='asia-south1'
DATABASE='evidencedesk'
BUCKET="$PROJECT-evidencedesk"
REPOSITORY='evidencedesk'
WEB_SERVICE='evidencedesk-web'
WORKER_JOB='evidencedesk-worker'
WEB_SA="evidencedesk-web@$PROJECT.iam.gserviceaccount.com"
WORKER_SA="evidencedesk-worker@$PROJECT.iam.gserviceaccount.com"
BUILD_SA="evidencedesk-build@$PROJECT.iam.gserviceaccount.com"
IMAGE_BASE="$REGION-docker.pkg.dev/$PROJECT/$REPOSITORY/app"
APPLY=0
run() { printf '+ '; printf '%q ' "$@"; printf '\n'; if [[ "$APPLY" == 1 ]]; then "$@"; fi; }
require_cli() { command -v gcloud >/dev/null || { printf 'Install Google Cloud CLI first.\n' >&2; exit 1; }; }
require_approval_notice() { if [[ "$APPLY" == 1 ]]; then printf 'Applying the listed resource changes. Review and authorize the exact resource plan before applying.\n' >&2; else printf 'PLAN ONLY. No cloud changes. Use --apply only after reviewing and authorizing this plan.\n' >&2; fi; }
