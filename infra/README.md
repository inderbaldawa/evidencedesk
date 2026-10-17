# Deploy EvidenceDesk on Google Cloud

These scripts prepare a compact Cloud Run deployment. They print commands by default. Review and configure your own project before using `--apply`; no credentials are included.

## Configuration

Set the following values in your shell:

```sh
export GOOGLE_CLOUD_PROJECT='your-gcp-project'
export GOOGLE_CLOUD_PROJECT_NUMBER='YOUR_PROJECT_NUMBER'
```

The default resource region is Mumbai (`asia-south1`). The named Firestore database is `evidencedesk`, the Cloud Run web service is `evidencedesk-web`, and the private worker job is `evidencedesk-worker`. The storage bucket is `${GOOGLE_CLOUD_PROJECT}-evidencedesk`. Review `common.sh` and `environment.example` before changing these conventions.

The model uses the `global` endpoint. Regional application storage does not make the complete pipeline India-resident.

## Resource and access plan

| Component | Configuration |
|---|---|
| Cloud Run web/API | Public website, authenticated private review APIs; 1 CPU, 512 MiB, minimum 0 and maximum 2 instances |
| Private Cloud Run Job | Durable analysis, one task per execution, one retry, 900-second timeout |
| Cloud Storage | Regional bucket, uniform access and public-access prevention |
| Firestore | Dedicated named database in Mumbai; existing default database untouched |
| Firebase Authentication | Dedicated Web app and anonymous identity for isolated writable sessions |
| Artifact Registry and Cloud Build | Private images, Linux amd64 build, dedicated build identity |
| Vertex AI Gemini | Worker identity only, global endpoint |

The web and worker identities receive access to the named database and application bucket. Only the worker receives Vertex AI access. The build identity receives image push access and access to the build-source object prefix. The API verifies Firebase identity and review ownership; browser Firestore rules deny direct database access.

Firebase revoked-token checks may need `roles/firebaseauth.viewer` for the web identity. This grants project-wide Authentication read visibility. Review that scope before choosing `--with-firebaseauth-viewer`; do not grant broad admin access merely to resolve a permission error.

## Deployment sequence

1. Verify billing, Cloud CLI authentication, project permissions and service availability. Inspect existing resource names so the scripts do not repurpose unrelated resources.
2. Run `bash infra/provision.sh` and inspect its plan. Use `--apply` only after accepting the listed changes. Inspect partial state before retrying a failed creation.
3. Register a dedicated Firebase Web app and configure anonymous sign-in as appropriate for your project. Save its public Web configuration in `infra/.local/firebase-web-config.json`. Do not supply a service-account key.
4. Deploy deny-all rules only to the named database using `firebase deploy --config infra/firebase.json --only firestore:evidencedesk --project "$GOOGLE_CLOUD_PROJECT"`.
5. Prepare a cloud budget ledger matching the validation schema in `app/backend/budget_cloud.py`. Set the model, reviewed prices, explicit limits and counters. Carry forward existing usage when migrating a local review. The local code currently uses 100 calls, 1,000,000 input tokens, 100,000 output tokens, a $10 cost ceiling and an $8 dispatch stop. Cloud limits come from the explicitly reviewed ledger; a proposed larger limit is not an active allocation. `python infra/initialize-budget.py FILE` inspects the target; `--apply` uses create-only semantics and never resets an existing ledger.
6. Run `python infra/render-env.py infra/.local/firebase-web-config.json`. It writes local environment files without printing their contents. The web service cannot dispatch model calls; the worker can only do so when its configured ledger permits them.
7. Run `python infra/stage-build.py`. Inspect the generated runtime-only `infra/.stage/BUILD_MANIFEST.json`, then review `bash infra/build.sh IMMUTABLE_TAG`. Use `--apply` to build when ready.
8. Resolve the actual image digest, then review `bash infra/deploy.sh sha256:DIGEST`. Use `--apply` only for the intended immutable image. Deployment does not execute a model request or fabricate a sample.
9. Seed a genuinely analyzed synthetic sample through the storage adapter, then test the deployed workflow, source pages, exports, identity isolation and a fresh analysis.

Dedicated runtime identities provide credentials. Never embed `GOOGLE_APPLICATION_CREDENTIALS`, downloaded keys, access tokens or local cloud configuration in the image.

## Validation and operations

Verify actual service/job identities, limits, IAM scope, database selection, private bucket access, Firebase revocation checks and persisted progress. Confirm two separate sessions cannot access each other's private reviews. Verify the sample anonymously and inspect failure/duplicate handling. A disabled budget ledger must reject dispatch.

Job parallelism is per execution. Concurrent execution limits need application controls and transaction-backed accounting. Billing alerts are notifications, not hard spending caps. Actual model pricing and operating costs must be checked for the project and workload.

`rollback.sh` takes an explicitly selected earlier web revision and worker digest. It changes code routing and future jobs, not stored reviews or budget history. Inspect already-running jobs separately.

`teardown.sh` is destructive and is not part of routine deployment. It requires `--apply --delete-evidencedesk-data`. Preserve artifacts you need first, and retain the judging deployment for the required period. Do not delete unrelated Firebase apps, users, the default database or the project. Soft-deleted objects and retained logs may remain billable.

Cloud readiness is determined by actual deployment checks, not the presence of these scripts. See `evals/README.md` for the current verification boundary.

## Deployment verification helpers

`seed_sample.py` validates a completed synthetic compact analysis and its exact source hashes, then creates the read-only cloud sample and private source objects only with `--apply --source-sha256 HASH`. Set `GOOGLE_CLOUD_PROJECT`; the default plan performs no cloud calls. Its default source is the raw local output from `evals/run_compact.py`, not an expected fixture.

`verify_deployment.py` defaults to a no-network plan. Use `--url HTTPS_RUN_APP_ORIGIN --read-only --resources` for public/resource checks. `--exercise` creates two anonymous accounts and private synthetic review artifacts; `--allow-ai --resources --exercise` additionally dispatches one real billable analysis through the configured shared cloud budget. Read its help and review limits before running. No tokens are printed or saved; created test reviews are not automatically deleted.
