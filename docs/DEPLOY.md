# Deployment

Infrastructure is provisioned once with `terraform/deploy.sh`. Application code
ships continuously: a merge to `main` that touches `api/` or `bot/` builds a new
image and rolls it out to Cloud Run via
[`.github/workflows/deploy.yml`](../.github/workflows/deploy.yml).

The split is deliberate. The pipeline only ever runs `gcloud run deploy` on the
two services. The VM, Atlas, and the GCS buckets stay manual: the VM's startup
script is ForceNew (a re-apply would recreate it and wipe OpenD's credentials and
cron), and the database is stateful. Nothing there should move because code
merged.

Terraform still owns each Cloud Run service's configuration (env, secrets,
scaling); it just ignores the running image (`ignore_changes` on
`template[0].containers[0].image`), so the pipeline owns deploys and a later
`terraform apply` will not revert them.

## One-time setup (Workload Identity Federation)

The pipeline authenticates with WIF — no long-lived key. Run these once as a
project owner. Substitute nothing; the values are this project's.

```bash
PROJECT=trade-compass-495804
PROJECT_NUMBER=647831890952
REPO=PCBZ/trade-compass
REGION=us-west1

# 1. A dedicated deployer service account
gcloud iam service-accounts create gh-deployer \
  --project "$PROJECT" \
  --display-name "GitHub Actions deployer"

DEPLOYER="gh-deployer@${PROJECT}.iam.gserviceaccount.com"

# 2. Roles it needs: build images, push them, deploy Cloud Run, act as the
#    runtime service accounts, and stage build sources.
for ROLE in \
  roles/run.admin \
  roles/cloudbuild.builds.editor \
  roles/artifactregistry.writer \
  roles/storage.admin \
  roles/iam.serviceAccountUser
do
  gcloud projects add-iam-policy-binding "$PROJECT" \
    --member "serviceAccount:${DEPLOYER}" --role "$ROLE" --condition=None
done

# 3. Workload Identity pool + a provider that trusts this GitHub repo
gcloud iam workload-identity-pools create github \
  --project "$PROJECT" --location global --display-name "GitHub"

gcloud iam workload-identity-pools providers create-oidc github-actions \
  --project "$PROJECT" --location global \
  --workload-identity-pool github \
  --display-name "GitHub Actions" \
  --issuer-uri "https://token.actions.githubusercontent.com" \
  --attribute-mapping "google.subject=assertion.sub,attribute.repository=assertion.repository" \
  --attribute-condition "assertion.repository == '${REPO}'"

# 4. Let identities from this repo impersonate the deployer SA
POOL="projects/${PROJECT_NUMBER}/locations/global/workloadIdentityPools/github"
gcloud iam service-accounts add-iam-policy-binding "$DEPLOYER" \
  --project "$PROJECT" \
  --role roles/iam.workloadIdentityUser \
  --member "principalSet://iam.googleapis.com/${POOL}/attribute.repository/${REPO}"
```

## Repository configuration

Add these as **repository variables** (Settings → Secrets and variables →
Actions → Variables). They are identifiers, not secrets — WIF's trust policy is
what gates access, not their obscurity.

| Variable | Value |
|----------|-------|
| `GCP_PROJECT_ID` | `trade-compass-495804` |
| `WIF_PROVIDER` | `projects/647831890952/locations/global/workloadIdentityPools/github/providers/github-actions` |
| `WIF_SERVICE_ACCOUNT` | `gh-deployer@trade-compass-495804.iam.gserviceaccount.com` |

## What the pipeline does not cover

- **First-time provisioning** and any infra change: `terraform/deploy.sh`.
- **The sync script on the VM.** It is pulled from GCS at VM bootstrap and does
  not auto-update; after changing `sync/`, upload it and refresh the VM by hand
  (see the main README).
- **Rollback.** Cloud Run keeps revisions — roll back in the console or with
  `gcloud run services update-traffic trade-compass-bot --to-revisions REV=100`.
