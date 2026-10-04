#!/usr/bin/env bash
# Deploy the Cloud Run image to a temporary GKE Autopilot cluster, for the Step 8 check only.
# Usage: PROJECT=<gcp project> REGION=us-central1 deploy/gke.sh up | down
set -euo pipefail
: "${PROJECT:?set PROJECT}" "${REGION:?set REGION}"
cd "$(git rev-parse --show-toplevel)"
# gcloud installs kubectl and the GKE auth plugin into its own bin directory.
PATH="$(dirname "$(readlink -f "$(command -v gcloud)")"):$PATH"
cluster=cuad-check

case "${1:-}" in
  up)
    image="$(gcloud run services describe clause-review-api --project "$PROJECT" --region "$REGION" \
      --format='value(spec.template.spec.containers[0].image)')"
    echo "image $image"
    gcloud container clusters create-auto "$cluster" --project "$PROJECT" --region "$REGION"
    gcloud container clusters get-credentials "$cluster" --project "$PROJECT" --region "$REGION"
    sed "s|IMAGE|${image}|" deploy/k8s/deployment.yaml | kubectl apply -f -
    kubectl apply -f deploy/k8s/service.yaml
    kubectl rollout status deployment/clause-review-api --timeout=20m
    until ip="$(kubectl get service clause-review-api -o jsonpath='{.status.loadBalancer.ingress[0].ip}')" && [ -n "$ip" ]; do
      sleep 10
    done
    echo "url http://${ip}"
    ;;
  down)
    gcloud container clusters delete "$cluster" --project "$PROJECT" --region "$REGION" --quiet
    gcloud container clusters list --project "$PROJECT"
    ;;
  *)
    echo "usage: deploy/gke.sh up | down" >&2
    exit 2
    ;;
esac
