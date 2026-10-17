# Deployment

`terraform/deploy.sh` provisions everything once. After that, pushing a `v*` tag
applies `terraform/bootstrap` (project APIs and the deployer's own roles) and
then both Cloud Run modules, via
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

# Just enough to let it apply terraform/bootstrap, which then manages the full
# role list itself. Do not extend this list here — add roles to
# google_project_iam_member.deployer in terraform/bootstrap/main.tf instead, or
# it drifts (that is how roles/viewer went missing from this doc for months).
for ROLE in resourcemanager.projectIamAdmin storage.admin \
  serviceusage.serviceUsageAdmin; do
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

## Bootstrap state

`terraform/bootstrap` creates the state bucket, so its own state cannot start
there. On a new project the first apply is local, then it moves in:

```bash
cd terraform/bootstrap
terraform init -backend=false
terraform apply -var="gcp_project_id=${PROJECT}"

terraform init -migrate-state \
  -backend-config="bucket=trade-compass-tfstate-${PROJECT}" \
  -backend-config="prefix=bootstrap"
```

This repo already had a local `terraform.tfstate` here from its first
provisioning, so the migrate step must be run once from that machine — CI
cannot migrate state it does not have, and without it the deploy would try to
create a bucket that already exists.

## Repository config

Settings → Secrets and variables → Actions.

**Variables:** `GCP_PROJECT_ID`, `WIF_PROVIDER`
(`projects/647831890952/locations/global/workloadIdentityPools/github/providers/github-actions`),
`WIF_SERVICE_ACCOUNT` (the `gh-deployer@…` email), `SEC_CONTACT` (your email).

**Secrets** (written into Secret Manager on each apply):
`TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, `FMP_API_KEY`, `OPENROUTER_API_KEY`.
