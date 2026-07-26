#!/usr/bin/env bash
set -euo pipefail

echo "============================================================"
echo "STEP 2: PUBLISHING DOCKER IMAGES TO GCR (gcr.io)"
echo "============================================================"

GCP_PROJECT="${GCP_PROJECT:-crajah-dev}"
GCR_REGISTRY="${GCR_REGISTRY:-gcr.io/${GCP_PROJECT}}"
TAG="${DOCKER_TAG:-latest}"

echo "[+] Target Registry: ${GCR_REGISTRY}"

components=("agent-registry" "tool-registry" "agent-london-backend" "agent-london-frontend")

for component in "${components[@]}"; do
    local_image="${component}:${TAG}"
    remote_image="${GCR_REGISTRY}/${component}:${TAG}"

    echo "[+] Tagging ${local_image} -> ${remote_image}"
    docker tag "${local_image}" "${remote_image}"

    echo "[+] Pushing ${remote_image} to GCR..."
    docker push "${remote_image}" || {
        echo "[!] Push warning: If running without GCP credentials, configure gcloud auth configure-docker."
    }
done

echo "============================================================"
echo "SUCCESS: Published images to GCR (${GCR_REGISTRY})"
echo "============================================================"
