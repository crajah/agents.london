#!/usr/bin/env bash
set -euo pipefail

echo "============================================================"
echo "STEP 2: PUBLISHING DOCKER IMAGES TO GCR (gcr.io)"
echo "============================================================"

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TAG_FILE="${PROJECT_ROOT}/.docker_tag"

GCP_PROJECT="${GCP_PROJECT:-marty-457112}"
GCR_REGISTRY="${GCR_REGISTRY:-gcr.io/${GCP_PROJECT}}"

if [ -n "${DOCKER_TAG:-}" ]; then
    TAG="${DOCKER_TAG}"
elif [ -f "${TAG_FILE}" ]; then
    TAG="$(cat "${TAG_FILE}")"
else
    TAG="$(date +'%y%m%d.%H%M%S')"
    echo "${TAG}" > "${TAG_FILE}"
fi

export DOCKER_TAG="${TAG}"
echo "[+] Target Registry: ${GCR_REGISTRY} | Image Tag: ${TAG}"

components=("agent-registry" "tool-registry" "document-registry-service" "agent-london-backend" "agent-london-frontend")

for component in "${components[@]}"; do
    local_image="${component}:${TAG}"
    remote_tagged="${GCR_REGISTRY}/${component}:${TAG}"
    remote_latest="${GCR_REGISTRY}/${component}:latest"

    echo "[+] Tagging ${local_image} -> ${remote_tagged}"
    docker tag "${local_image}" "${remote_tagged}"

    echo "[+] Pushing ${remote_tagged} to GCR..."
    docker push "${remote_tagged}"

    if [ "${TAG}" != "latest" ]; then
        echo "[+] Tagging ${local_image} -> ${remote_latest}"
        docker tag "${local_image}" "${remote_latest}"
        echo "[+] Pushing ${remote_latest} to GCR..."
        docker push "${remote_latest}"
    fi
done

echo "============================================================"
echo "SUCCESS: Published images to GCR (${GCR_REGISTRY})"
echo "============================================================"
