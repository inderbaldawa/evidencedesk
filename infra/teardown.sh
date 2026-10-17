#!/usr/bin/env bash
# Never run at submission time. Keep the demo available through judging.
set -euo pipefail
source "$(dirname "$0")/common.sh"
if [[ "${1:-}" == '--apply' ]]; then
  [[ "${2:-}" == '--delete-evidencedesk-data' ]] || { printf 'Destructive teardown requires --apply --delete-evidencedesk-data after separate authorization.\n' >&2; exit 2; }
  APPLY=1
elif [[ $# -gt 0 ]]; then printf 'Usage: %s [--apply --delete-evidencedesk-data]\n' "$0" >&2; exit 2; fi
require_cli
printf 'DESTRUCTIVE teardown plan: all EvidenceDesk reviews and source PDFs will be removed. Existing default Firestore and unrelated Firebase apps remain.\n' >&2
run gcloud run services delete "$WEB_SERVICE" --region="$REGION" --project="$PROJECT" --quiet
run gcloud run jobs delete "$WORKER_JOB" --region="$REGION" --project="$PROJECT" --quiet
run gcloud storage rm --recursive "gs://$BUCKET" --project="$PROJECT"
run gcloud firestore databases update --database="$DATABASE" --no-delete-protection --project="$PROJECT"
run gcloud firestore databases delete --database="$DATABASE" --project="$PROJECT" --quiet
run gcloud artifacts repositories delete "$REPOSITORY" --location="$REGION" --project="$PROJECT" --quiet
DB_CONDITION="expression=resource.name=='projects/$PROJECT/databases/$DATABASE',title=evidencedesk-database-only,description=Only the dedicated EvidenceDesk database"
for sa in "$WEB_SA" "$WORKER_SA"; do
  run gcloud projects remove-iam-policy-binding "$PROJECT" --member="serviceAccount:$sa" --role=roles/datastore.user --condition="$DB_CONDITION"
done
run gcloud projects remove-iam-policy-binding "$PROJECT" --member="serviceAccount:$WORKER_SA" --role=roles/aiplatform.user --condition=None
run gcloud projects remove-iam-policy-binding "$PROJECT" --member="serviceAccount:$BUILD_SA" --role=roles/logging.logWriter --condition=None
run gcloud projects remove-iam-policy-binding "$PROJECT" --member="serviceAccount:$BUILD_SA" --role=roles/serviceusage.serviceUsageConsumer --condition=None
for sa in "$WEB_SA" "$WORKER_SA" "$BUILD_SA"; do run gcloud iam service-accounts delete "$sa" --project="$PROJECT" --quiet; done
printf 'Manual follow-up: remove the dedicated Firebase Web app by recorded appId; remove optional firebaseauth.viewer binding if granted; inspect remaining named rules release and logs. Do not disable anonymous auth, delete shared users, disable project APIs, or delete the project. Soft-deleted storage can remain billable during its retention window.\n'
