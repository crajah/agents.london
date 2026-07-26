#!/usr/bin/env bash
set -euo pipefail

echo "============================================================"
echo "STEP 1: BUILDING DOCKER IMAGES FOR AGENT.LONDON COMPONENTS"
echo "============================================================"

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TAG="${DOCKER_TAG:-latest}"

echo "[+] Building agent-registry image..."
docker build -t "agent-registry:${TAG}" "${PROJECT_ROOT}/services/agent-registry"

echo "[+] Building tool-registry image..."
docker build -t "tool-registry:${TAG}" "${PROJECT_ROOT}/services/tool-registry"

echo "[+] Building backend BFF image..."
docker build -t "agent-london-backend:${TAG}" -f "${PROJECT_ROOT}/backend/Dockerfile" "${PROJECT_ROOT}"

echo "[+] Building frontend web visualizer image..."
docker build -t "agent-london-frontend:${TAG}" "${PROJECT_ROOT}/frontend"

echo "============================================================"
echo "SUCCESS: All 4 Docker images built locally with tag '${TAG}'"
echo "============================================================"
