# State lives in the bucket this module creates. On a brand-new project that is
# circular, so the first apply runs with `-backend=false` and the state is
# migrated in afterwards; see docs/DEPLOY.md.
terraform {
  backend "gcs" {}
}
