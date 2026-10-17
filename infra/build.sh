#!/usr/bin/env bash
set -euo pipefail
source "$(dirname "$0")/common.sh"
if [[ "${1:-}" == '--apply' ]]; then APPLY=1; shift; fi
TAG="${1:-}"
[[ "$TAG" =~ ^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$ ]] || { printf 'Usage: %s [--apply] immutable-tag\n' "$0" >&2; exit 2; }
require_cli
require_approval_notice
[[ -f "$INFRA_DIR/.stage/BUILD_MANIFEST.json" ]] || { printf 'Prepare and inspect stage-build.py output first.\n' >&2; exit 1; }
run gcloud builds submit "$INFRA_DIR/.stage" --config="$INFRA_DIR/.stage/infra/cloudbuild.yaml" --ignore-file="$INFRA_DIR/.stage/.gcloudignore" --region="$REGION" --gcs-source-staging-dir="gs://$BUCKET/build-source" --substitutions="_IMAGE=$IMAGE_BASE:$TAG" --project="$PROJECT"
printf 'After success, resolve and record the image digest, then deploy that digest (not a mutable tag).\n'
run gcloud artifacts docker images describe "$IMAGE_BASE:$TAG" --format='value(image_summary.digest)' --project="$PROJECT"
