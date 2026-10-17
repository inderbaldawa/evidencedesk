#!/usr/bin/env bash
set -euo pipefail
source "$(dirname "$0")/common.sh"
AUTH_VIEWER=0
for arg in "$@"; do case "$arg" in --apply) APPLY=1;; --with-firebaseauth-viewer) AUTH_VIEWER=1;; *) printf 'Usage: %s [--apply] [--with-firebaseauth-viewer]\n' "$0" >&2; exit 2;; esac; done
require_cli
require_approval_notice
run gcloud services enable run.googleapis.com cloudbuild.googleapis.com artifactregistry.googleapis.com firestore.googleapis.com storage.googleapis.com aiplatform.googleapis.com identitytoolkit.googleapis.com firebase.googleapis.com firebaserules.googleapis.com --project="$PROJECT"

# Creation commands intentionally fail on an existing resource. Inspect it and skip
# that individual creation on an approved retry; never silently repurpose one.
for account in evidencedesk-web evidencedesk-worker evidencedesk-build; do
  run gcloud iam service-accounts create "$account" --display-name="$account" --project="$PROJECT"
done
run gcloud artifacts repositories create "$REPOSITORY" --repository-format=docker --location="$REGION" --description='EvidenceDesk prototype images' --project="$PROJECT"
run gcloud storage buckets create "gs://$BUCKET" --location="$REGION" --uniform-bucket-level-access --public-access-prevention --project="$PROJECT"
run gcloud firestore databases create --database="$DATABASE" --location="$REGION" --type=firestore-native --delete-protection --project="$PROJECT"

DB_CONDITION="expression=resource.name=='projects/$PROJECT/databases/$DATABASE',title=evidencedesk-database-only,description=Only the dedicated EvidenceDesk database"
for sa in "$WEB_SA" "$WORKER_SA"; do
  run gcloud projects add-iam-policy-binding "$PROJECT" --member="serviceAccount:$sa" --role=roles/datastore.user --condition="$DB_CONDITION"
  run gcloud storage buckets add-iam-policy-binding "gs://$BUCKET" --member="serviceAccount:$sa" --role=roles/storage.objectAdmin --project="$PROJECT"
done
run gcloud projects add-iam-policy-binding "$PROJECT" --member="serviceAccount:$WORKER_SA" --role=roles/aiplatform.user --condition=None
run gcloud artifacts repositories add-iam-policy-binding "$REPOSITORY" --location="$REGION" --member="serviceAccount:$BUILD_SA" --role=roles/artifactregistry.writer --project="$PROJECT"
SOURCE_CONDITION="expression=resource.name.startsWith('projects/_/buckets/$BUCKET/objects/build-source/'),title=evidencedesk-build-source-only,description=Build archive prefix only"
run gcloud storage buckets add-iam-policy-binding "gs://$BUCKET" --member="serviceAccount:$BUILD_SA" --role=roles/storage.objectViewer --condition="$SOURCE_CONDITION" --project="$PROJECT"
run gcloud projects add-iam-policy-binding "$PROJECT" --member="serviceAccount:$BUILD_SA" --role=roles/logging.logWriter --condition=None
run gcloud projects add-iam-policy-binding "$PROJECT" --member="serviceAccount:$BUILD_SA" --role=roles/serviceusage.serviceUsageConsumer --condition=None
if [[ "$AUTH_VIEWER" == 1 ]]; then
  run gcloud projects add-iam-policy-binding "$PROJECT" --member="serviceAccount:$WEB_SA" --role=roles/firebaseauth.viewer --condition=None
fi
printf 'Next: operator must already have iam.serviceAccounts.actAs on the three dedicated identities. Do not grant broader project roles to fix a specific missing permission.\n'
printf 'Job-scoped execution role is applied by deploy.sh after job creation. Firebase app/rules and ledger are separate explicit steps.\n'
