#!/usr/bin/env bash
set -euo pipefail

echo "============================================================"
echo "STEP 3: DEPLOYING ALL AGENT.LONDON COMPONENTS TO KUBERNETES"
echo "============================================================"

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
K8S_DIR="${PROJECT_ROOT}/deploy/k8s"

echo "[+] 1. Deploying agent-registry service..."
kubectl apply -f "${K8S_DIR}/01-agent-registry.yaml"

echo "[+] 2. Deploying tool-registry service..."
kubectl apply -f "${K8S_DIR}/02-tool-registry.yaml"

echo "[+] 3. Deploying backend BFF service..."
kubectl apply -f "${K8S_DIR}/03-backend.yaml"

echo "[+] 4. Deploying frontend web visualizer service..."
kubectl apply -f "${K8S_DIR}/04-frontend.yaml"

echo "[+] 5. Deploying agents.london Ingress & Managed SSL Certificate..."
kubectl apply -f "${K8S_DIR}/05-ingress.yaml"

echo "[+] Verifying deployments rollout status..."
kubectl rollout status deployment/agent-registry --namespace default --timeout=180s
kubectl rollout status deployment/tool-registry --namespace default --timeout=180s
kubectl rollout status deployment/agent-london-backend --namespace default --timeout=180s
kubectl rollout status deployment/agent-london-frontend --namespace default --timeout=180s

echo "[+] Ingress Gateway & Managed Certificate Status:"
kubectl get ingress agents-london-ingress --namespace default || true
kubectl get managedcertificate agents-london-managed-cert --namespace default || true

echo "============================================================"
echo "SUCCESS: All agents.london components & Ingress deployed!"
echo "URL: https://agents.london"
echo "============================================================"
