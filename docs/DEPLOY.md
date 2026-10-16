# Deployment

`terraform/deploy.sh` provisions everything once. After that, pushing a `v*` tag
runs `terraform apply` on both Cloud Run modules via
[`deploy.yml`](../.github/workflows/deploy.yml). The VM and Atlas stay manual.

## Releasing

Merging to `main` does not deploy. Cut a release when you want one:

```bash
git tag v0.1.0
git push origin v0.1.0
```

Both modules apply on every tag. That is cheap: each image is tagged with a hash
of its source, so a component you did not touch rebuilds nothing and gets no new
revision. To deploy without tagging, run the workflow by hand from the Actions
tab.

## One-time WIF setup

Run once as project owner:

```bash
PROJECT=trade-compass-495804
PROJECT_NUMBER=647831890952
REPO=PCBZ/trade-compass
DEPLOYER="gh-deployer@${PROJECT}.iam.gserviceaccount.com"

gcloud iam service-accounts create gh-deployer --project "$PROJECT"

for ROLE in run.admin secretmanager.admin artifactregistry.admin \
  cloudbuild.builds.editor storage.admin iam.serviceAccountAdmin \
  iam.serviceAccountUser resourcemanager.projectIamAdmin; do
  gcloud projects add-iam-policy-binding "$PROJECT" \
    --member "serviceAccount:${DEPLOYER}" --role "roles/${ROLE}" --condition=None
done

gcloud iam workload-identity-pools create github --project "$PROJECT" --location global
gcloud iam workload-identity-pools providers create-oidc github-actions \
  --project "$PROJECT" --location global --workload-identity-pool github \
  --issuer-uri "https://token.actions.githubusercontent.com" \
  --attribute-mapping "google.subject=assertion.sub,attribute.repository=assertion.repository" \
  --attribute-condition "assertion.repository == '${REPO}'"

POOL="projects/${PROJECT_NUMBER}/locations/global/workloadIdentityPools/github"
gcloud iam service-accounts add-iam-policy-binding "$DEPLOYER" --project "$PROJECT" \
  --role roles/iam.workloadIdentityUser \
  --member "principalSet://iam.googleapis.com/${POOL}/attribute.repository/${REPO}"
```

## Repository config

Settings → Secrets and variables → Actions.

**Variables:** `GCP_PROJECT_ID`, `WIF_PROVIDER`
(`projects/647831890952/locations/global/workloadIdentityPools/github/providers/github-actions`),
`WIF_SERVICE_ACCOUNT` (the `gh-deployer@…` email), `SEC_CONTACT` (your email).

**Secrets** (written into Secret Manager on each apply):
`TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, `FMP_API_KEY`, `OPENROUTER_API_KEY`.
