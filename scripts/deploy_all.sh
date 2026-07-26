#!/usr/bin/env bash
set -euo pipefail

echo "============================================================"
echo "AGENT.LONDON FULL CI/CD DEPLOYMENT PIPELINE"
echo "1. Build Docker Images  |  2. Publish to GCR  |  3. Deploy to K8s"
echo "============================================================"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

bash "${SCRIPT_DIR}/01_build_docker.sh"
bash "${SCRIPT_DIR}/02_publish_gcr.sh"
bash "${SCRIPT_DIR}/03_deploy_k8s.sh"

echo "============================================================"
echo "PIPELINE COMPLETED SUCCESSFULLY!"
echo "============================================================"
