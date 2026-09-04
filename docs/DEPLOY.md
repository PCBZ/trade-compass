# Deployment

Infrastructure is provisioned once with `terraform/deploy.sh`. Application code
then ships continuously: a merge to `main` that touches `api/` or `bot/` runs
`terraform apply` on that module via
[`.github/workflows/deploy.yml`](../.github/workflows/deploy.yml), the same path
`deploy.sh` takes.

The split is deliberate. The pipeline only applies the two Cloud Run modules
(`terraform/cloud_run`, `terraform/bot`). The VM (`terraform/compute_engine`),
Atlas, and the buckets stay manual: the VM's startup script is ForceNew — a
re-apply recreates the instance and wipes OpenD's credentials and cron — and the
database is stateful. Nothing there should move because code merged.

Because it is Terraform rather than a bare `gcloud run deploy`, each apply
reconciles the whole module — the Cloud Run service, its Secret Manager secrets,
IAM bindings, and the runtime service account — not just the image. That keeps
Terraform the single source of truth (no image drift), at the cost of a broader
deployer role and the app secrets living in GitHub, below.

## One-time setup (Workload Identity Federation)

The pipeline authenticates with WIF — no long-lived key. Run these once as a
project owner; the values are this project's.

```bash
PROJECT=trade-compass-495804
PROJECT_NUMBER=647831890952
REPO=PCBZ/trade-compass

# 1. A dedicated deployer service account
gcloud iam service-accounts create gh-deployer \
  --project "$PROJECT" --display-name "GitHub Actions deployer"

DEPLOYER="gh-deployer@${PROJECT}.iam.gserviceaccount.com"

# 2. Roles. Broad, because `terraform apply` reconciles the full module: Cloud
#    Run, Secret Manager (it writes the secret versions from the passed vars),
#    IAM bindings, the runtime service accounts, Artifact Registry, Cloud Build,
#    and the Terraform state in GCS.
for ROLE in \
  roles/run.admin \
  roles/secretmanager.admin \
  roles/artifactregistry.admin \
  roles/cloudbuild.builds.editor \
  roles/storage.admin \
  roles/iam.serviceAccountAdmin \
  roles/iam.serviceAccountUser \
  roles/resourcemanager.projectIamAdmin
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

Settings → Secrets and variables → Actions.

**Variables** (identifiers, not sensitive — WIF's trust policy gates access):

| Variable | Value |
|----------|-------|
| `GCP_PROJECT_ID` | `trade-compass-495804` |
| `WIF_PROVIDER` | `projects/647831890952/locations/global/workloadIdentityPools/github/providers/github-actions` |
| `WIF_SERVICE_ACCOUNT` | `gh-deployer@trade-compass-495804.iam.gserviceaccount.com` |
| `SEC_CONTACT` | your contact email for SEC EDGAR |

**Secrets** — the bot module writes these into Secret Manager on each apply, so
the pipeline needs the values, exactly as `deploy.sh` reads them from `bot/.env`:

| Secret | From |
|--------|------|
| `TELEGRAM_BOT_TOKEN` | BotFather |
| `TELEGRAM_CHAT_ID` | your chat ID |
| `FMP_API_KEY` | Financial Modeling Prep |
| `OPENROUTER_API_KEY` | OpenRouter |

## What the pipeline does not cover

- **First-time provisioning** and any infra change: `terraform/deploy.sh`.
- **The sync script on the VM.** Pulled from GCS at VM bootstrap; it does not
  auto-update. After changing `sync/`, upload it and refresh the VM by hand (see
  the main README).
- **Rollback.** Cloud Run keeps revisions — roll back in the console or with
  `gcloud run services update-traffic trade-compass-bot --to-revisions REV=100`.
