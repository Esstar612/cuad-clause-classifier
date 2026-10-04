#!/usr/bin/env bash
# Deploy the Cloud Run image to a temporary GKE Autopilot cluster, for the Step 8 check only.
# Usage: PROJECT=<gcp project> REGION=us-central1 deploy/gke.sh check | up | down
#   check  create the cluster, run the parity check, and always delete the cluster afterwards
#   up     create and deploy only (then delete it with `down`: an idle cluster still bills)
set -euo pipefail
: "${PROJECT:?set PROJECT}" "${REGION:?set REGION}"
cd "$(git rev-parse --show-toplevel)"
# gcloud installs kubectl and the GKE auth plugin into its own bin directory.
PATH="$(dirname "$(readlink -f "$(command -v gcloud)")"):$PATH"
cluster=cuad-check

up() {
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
}

down() {
  # Retried: a delete during provisioning fails, and a cluster left behind keeps billing.
  for _ in $(seq 1 20); do
    gcloud container clusters delete "$cluster" --project "$PROJECT" --region "$REGION" --quiet && break
    gcloud container clusters describe "$cluster" --project "$PROJECT" --region "$REGION" >/dev/null 2>&1 || break
    sleep 30
  done
  gcloud container clusters list --project "$PROJECT"
}

case "${1:-}" in
  check)
    trap down EXIT
    up
    until curl -sf -m 10 "http://${ip}/health"; do sleep 10; done; echo
    python -m scripts.deploy_parity --url "http://${ip}" --target gke 2>&1 | tee data/processed/deploy_parity_gke.txt
    ;;
  up) up ;;
  down) down ;;
  *)
    echo "usage: deploy/gke.sh check | up | down" >&2
    exit 2
    ;;
esac
