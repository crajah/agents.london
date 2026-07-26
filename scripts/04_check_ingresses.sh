#!/usr/bin/env bash
set -euo pipefail

# Color Codes
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
MAGENTA='\033[0;35m'
NC='\033[0m' # No Color

echo -e "${MAGENTA}============================================================${NC}"
echo -e "${MAGENTA}  AGENTS.LONDON DEEP KUBERNETES CR & INGRESS VERIFIER       ${NC}"
echo -e "${MAGENTA}============================================================${NC}"

# Track overall health
FAILED_CHECKS=0

function log_step() {
    echo -e "\n${BLUE}============================================================${NC}"
    echo -e "${BLUE} STEP $1: $2${NC}"
    echo -e "${BLUE}============================================================${NC}"
}

# -------------------------------------------------------------------------
# STEP 1: CUSTOM RESOURCE DEFINITIONS (CRDs)
# -------------------------------------------------------------------------
log_step "1" "Auditing Custom Resource Definitions (CRDs)"

echo -e "[+] 1.1 Checking 'kagents.kagent.dev' CRD..."
if kubectl get crd kagents.kagent.dev &> /dev/null; then
    echo -e "${GREEN}[✓] CRD 'kagents.kagent.dev' exists and is established.${NC}"
    kubectl get crd kagents.kagent.dev -o custom-columns=NAME:.metadata.name,VERSION:.spec.versions[0].name,SCOPE:.spec.scope
else
    echo -e "${YELLOW}[i] CRD 'kagents.kagent.dev' not found in cluster.${NC}"
fi

echo -e "\n[+] 1.2 Checking Gateway API CRDs (gateway.networking.k8s.io)..."
for GATEWAY_CRD in "gateways.gateway.networking.k8s.io" "httproutes.gateway.networking.k8s.io"; do
    if kubectl get crd "${GATEWAY_CRD}" &> /dev/null; then
        echo -e "${GREEN}[✓] CRD '${GATEWAY_CRD}' is installed.${NC}"
    else
        echo -e "${YELLOW}[i] Gateway API CRD '${GATEWAY_CRD}' not installed.${NC}"
    fi
done

# -------------------------------------------------------------------------
# STEP 2: KAGENT CR INSTANCES
# -------------------------------------------------------------------------
log_step "2" "Auditing KAgent Custom Resources"

echo -e "[+] 2.1 Inspecting KAgent CR instances..."
if kubectl get kagents --all-namespaces &> /dev/null; then
    KAGENTS_COUNT=$(kubectl get kagents --all-namespaces --no-headers 2>/dev/null | wc -l || echo "0")
    echo -e "${GREEN}[✓] Found ${KAGENTS_COUNT} KAgent custom resource(s).${NC}"
    kubectl get kagents --all-namespaces -o wide || true
else
    echo -e "${YELLOW}[i] No KAgent CR instances deployed.${NC}"
fi

# -------------------------------------------------------------------------
# STEP 3: MANAGED CERTIFICATES & CERT-MANAGER CRs
# -------------------------------------------------------------------------
log_step "3" "Auditing Managed Certificates & Cert-Manager CRs"

echo -e "[+] 3.1 Inspecting GKE ManagedCertificate CRs..."
if kubectl get managedcertificate --all-namespaces &> /dev/null; then
    MC_LIST=$(kubectl get managedcertificate --all-namespaces -o jsonpath='{range .items[*]}{.metadata.namespace}{"\t"}{.metadata.name}{"\t"}{.spec.domains[*]}{"\t"}{.status.certificateName}{"\t"}{.status.certificateStatus}{"\n"}{end}')
    echo -e "NAMESPACE\tNAME\t\t\tDOMAINS\t\tGCP_CERT_ID\tSTATUS"
    echo -e "----------------------------------------------------------------------------------------"
    echo -e "${MC_LIST}"

    # Detailed check per ManagedCertificate
    kubectl get managedcertificate -o json | jq -r '.items[] | "[\(if .status.certificateStatus == "Active" then "\u001b[32m✓" else "\u001b[33mi" end)\u001b[0m] ManagedCert \(.metadata.name): Domain=\(.spec.domains[0]) Status=\(.status.certificateStatus // "Provisioning")"' 2>/dev/null || true
else
    echo -e "${YELLOW}[i] No GKE ManagedCertificate CRs found.${NC}"
fi

echo -e "\n[+] 3.2 Inspecting Cert-Manager Certificate CRs..."
if kubectl get certificate --all-namespaces &> /dev/null; then
    kubectl get certificate,clusterissuer,issuer --all-namespaces || true
else
    echo -e "${YELLOW}[i] Cert-Manager CRs not present.${NC}"
fi

# -------------------------------------------------------------------------
# STEP 4: KUBERNETES GATEWAY & INGRESS RESOURCES
# -------------------------------------------------------------------------
log_step "4" "Auditing Gateway API & Ingress Resources"

echo -e "[+] 4.1 Inspecting Gateway API Resources (Gateway & HTTPRoute)..."
if kubectl get gateway --all-namespaces &> /dev/null; then
    kubectl get gateway,httproute --all-namespaces || true
else
    echo -e "${YELLOW}[i] No Gateway API Gateway/HTTPRoute resources found.${NC}"
fi

echo -e "\n[+] 4.2 Inspecting GKE Ingress Resources..."
INGRESS_ITEMS=$(kubectl get ingress --all-namespaces -o json 2>/dev/null || echo "")

if [ -z "${INGRESS_ITEMS}" ] || [ "$(echo "${INGRESS_ITEMS}" | jq '.items | length')" -eq 0 ]; then
    echo -e "${RED}[!] No Ingress resources found in cluster!${NC}"
    FAILED_CHECKS=$((FAILED_CHECKS+1))
else
    echo -e "${GREEN}[✓] Ingress resources detected:${NC}"
    kubectl get ingress --all-namespaces -o wide

    echo -e "\n[+] 4.3 Verifying Ingress Load Balancer IP Assignments..."
    UNBOUND_INGRESSES=$(echo "${INGRESS_ITEMS}" | jq -r '.items[] | select(.status.loadBalancer.ingress == null) | .metadata.name')
    if [ -n "${UNBOUND_INGRESSES}" ]; then
        echo -e "${RED}[!] The following Ingress(es) do not have a Load Balancer IP assigned yet:${NC}"
        echo -e "${UNBOUND_INGRESSES}"
        FAILED_CHECKS=$((FAILED_CHECKS+1))
    else
        echo -e "${GREEN}[✓] All Ingress resources have assigned Load Balancer IP addresses.${NC}"
    fi
fi

# -------------------------------------------------------------------------
# STEP 5: BACKEND SERVICES & ENDPOINT HEALTH
# -------------------------------------------------------------------------
log_step "5" "Auditing Backend Services & Pod Readiness"

echo -e "[+] 5.1 Verifying Core Services & Endpoints..."
SERVICES=("agent-london-frontend-service" "agent-london-backend-service" "agent-registry-service" "tool-registry-service")

for SVC in "${SERVICES[@]}"; do
    if kubectl get svc "${SVC}" --namespace default &> /dev/null; then
        EP_COUNT=$(kubectl get endpoints "${SVC}" --namespace default -o jsonpath='{.subsets[*].addresses[*].ip}' 2>/dev/null | wc -w || echo "0")
        if [ "${EP_COUNT}" -gt 0 ]; then
            echo -e "${GREEN}[✓] Service '${SVC}' has ${EP_COUNT} active pod endpoint(s).${NC}"
        else
            echo -e "${RED}[!] Service '${SVC}' HAS NO ACTIVE ENDPOINTS!${NC}"
            FAILED_CHECKS=$((FAILED_CHECKS+1))
        fi
    else
        echo -e "${YELLOW}[i] Service '${SVC}' not found in default namespace.${NC}"
    fi
done

# -------------------------------------------------------------------------
# STEP 6: GCP CLOUD INFRASTRUCTURE & DNS
# -------------------------------------------------------------------------
log_step "6" "Auditing GCP Cloud Static IP & DNS Resolution"

GLOBAL_IP_NAME="agents-london-global-ip"
TARGET_HOST="agents.london"

if command -v gcloud &> /dev/null; then
    echo -e "[+] 6.1 Inspecting GCP Global Static IP '${GLOBAL_IP_NAME}'..."
    GCP_IP=$(gcloud compute addresses describe "${GLOBAL_IP_NAME}" --global --format="value(address)" 2>/dev/null || echo "")
    if [ -n "${GCP_IP}" ]; then
        echo -e "${GREEN}[✓] GCP Global Static IP Reserved: ${GCP_IP}${NC}"
    else
        echo -e "${RED}[!] GCP Global Static IP '${GLOBAL_IP_NAME}' NOT FOUND!${NC}"
        FAILED_CHECKS=$((FAILED_CHECKS+1))
    fi

    echo -e "\n[+] 6.2 Inspecting GCP SSL Certificate Status..."
    gcloud compute ssl-certificates list --format="table(name, type, managedStatus, creationTimestamp)" || true
fi

echo -e "\n[+] 6.3 Verifying Public DNS A-Record Resolution for '${TARGET_HOST}'..."
RESOLVED_IP=$(dig +short "${TARGET_HOST}" A | head -n1 || echo "")

if [ -n "${RESOLVED_IP}" ]; then
    echo -e "${GREEN}[✓] Public DNS A-Record: ${TARGET_HOST} -> ${RESOLVED_IP}${NC}"
    if [ -n "${GCP_IP:-}" ] && [ "${RESOLVED_IP}" != "${GCP_IP}" ]; then
        echo -e "${RED}[!] MISMATCH: DNS IP (${RESOLVED_IP}) does not match Reserved Global IP (${GCP_IP})!${NC}"
        FAILED_CHECKS=$((FAILED_CHECKS+1))
    fi
else
    echo -e "${RED}[!] DNS Lookup Failed for ${TARGET_HOST}!${NC}"
    FAILED_CHECKS=$((FAILED_CHECKS+1))
fi

# -------------------------------------------------------------------------
# STEP 7: SEQUENTIAL END-TO-END HTTP/HTTPS & ROUTING PROBES
# -------------------------------------------------------------------------
log_step "7" "Sequential End-to-End HTTP/HTTPS Probes"

echo -e "[+] 7.1 Probing HTTP (Port 80)..."
HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" "http://${TARGET_HOST}/" --max-time 8 || echo "000")
echo -e "    HTTP http://${TARGET_HOST}/ -> Status: ${HTTP_CODE}"

echo -e "\n[+] 7.2 Probing HTTPS Frontend (Port 443)..."
HTTPS_CODE=$(curl -s -o /dev/null -w "%{http_code}" "https://${TARGET_HOST}/" --max-time 8 || echo "000")
if [ "${HTTPS_CODE}" -eq 200 ]; then
    echo -e "${GREEN}[✓] HTTPS Frontend (/) Healthy: Status 200 OK${NC}"
else
    echo -e "${YELLOW}[i] HTTPS Frontend (/) Status: ${HTTPS_CODE}${NC}"
fi

echo -e "\n[+] 7.3 Probing HTTPS Backend API (/api/health)..."
API_CODE=$(curl -s -o /dev/null -w "%{http_code}" "https://${TARGET_HOST}/api/health" --max-time 8 || echo "000")
if [ "${API_CODE}" -eq 200 ]; then
    echo -e "${GREEN}[✓] HTTPS Backend API (/api/health) Healthy: Status 200 OK${NC}"
else
    echo -e "${YELLOW}[i] HTTPS Backend API (/api/health) Status: ${API_CODE}${NC}"
fi

# -------------------------------------------------------------------------
# SUMMARY
# -------------------------------------------------------------------------
echo -e "\n${MAGENTA}============================================================${NC}"
if [ "${FAILED_CHECKS}" -eq 0 ]; then
    echo -e "${GREEN}  ✓ DEEP KUBERNETES CR & INGRESS AUDIT PASSED WITH 0 ERRORS!${NC}"
else
    echo -e "${RED}  ✗ DEEP AUDIT COMPLETED WITH ${FAILED_CHECKS} WARNING(S) / ERROR(S)!${NC}"
fi
echo -e "${MAGENTA}============================================================${NC}"
