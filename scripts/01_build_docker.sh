#!/usr/bin/env bash
set -euo pipefail

echo "============================================================"
echo "STEP 1: BUILDING DOCKER IMAGES FOR AGENT.LONDON COMPONENTS"
echo "============================================================"

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TAG_FILE="${PROJECT_ROOT}/.docker_tag"

if [ -n "${DOCKER_TAG:-}" ]; then
    TAG="${DOCKER_TAG}"
elif [ -f "${TAG_FILE}" ]; then
    TAG="$(cat "${TAG_FILE}")"
else
    TAG="$(date +'%y%m%d.%H%M%S')"
    echo "${TAG}" > "${TAG_FILE}"
fi

export DOCKER_TAG="${TAG}"
echo "[+] Docker Image Tag: ${TAG}"

echo "[+] Building agent-registry image..."
docker build -t "agent-registry:${TAG}" -f "${PROJECT_ROOT}/services/agent-registry/Dockerfile" "${PROJECT_ROOT}"

echo "[+] Building tool-registry image..."
docker build -t "tool-registry:${TAG}" "${PROJECT_ROOT}/services/tool-registry"

echo "[+] Building document-registry service image..."
docker build -t "document-registry-service:${TAG}" "${PROJECT_ROOT}/services/document-registry"

echo "[+] Building backend BFF image..."
docker build -t "agent-london-backend:${TAG}" "${PROJECT_ROOT}/backend"

echo "[+] Building frontend web visualizer image..."
# VITE_GOOGLE_CLIENT_ID and VITE_MS_CLIENT_ID must be set as env vars
# (from GitHub Actions secrets or local .env) before running this script
docker build \
    --build-arg VITE_GOOGLE_CLIENT_ID="${VITE_GOOGLE_CLIENT_ID:-}" \
    --build-arg VITE_MS_CLIENT_ID="${VITE_MS_CLIENT_ID:-}" \
    -t "agent-london-frontend:${TAG}" "${PROJECT_ROOT}/frontend"

echo "============================================================"
echo "SUCCESS: All 5 Docker images built locally with tag '${TAG}'"
echo "============================================================"
