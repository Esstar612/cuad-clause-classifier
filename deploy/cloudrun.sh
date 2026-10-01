#!/usr/bin/env bash
# Build the image with Cloud Build and deploy it to Cloud Run (Step 8).
# Usage: PROJECT=<gcp project> REGION=us-central1 [SERVICE_CORS_ORIGINS=https://x.vercel.app] deploy/cloudrun.sh
set -euo pipefail
: "${PROJECT:?set PROJECT}" "${REGION:?set REGION}"
cd "$(git rev-parse --show-toplevel)"

image="${REGION}-docker.pkg.dev/${PROJECT}/cuad/service:$(git rev-parse --short HEAD)"
gcloud builds submit --project "$PROJECT" --region "$REGION" --tag "$image" .
digest="$(gcloud artifacts docker images describe "$image" --project "$PROJECT" --format='value(image_summary.digest)')"
echo "image ${image%%:*}@${digest}"

gcloud run deploy cuad-review --project "$PROJECT" --region "$REGION" \
  --image "${image%%:*}@${digest}" \
  --cpu 2 --memory 8Gi --max-instances 1 --min-instances 0 --concurrency 4 --timeout 900 --cpu-boost \
  --allow-unauthenticated \
  --set-env-vars "^|^SERVICE_CORS_ORIGINS=${SERVICE_CORS_ORIGINS:-}"
gcloud run services describe cuad-review --project "$PROJECT" --region "$REGION" --format='value(status.url)'
