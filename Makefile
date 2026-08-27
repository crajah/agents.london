# agents.london — local development & deployment
#
#   make setup     — create venv, install all deps
#   make dev       — run backend + frontend dev servers
#   make test      — run integration tests
#   make deploy    — build, push to GCR, apply K8s manifests
#   make clean     — remove venv, node_modules, caches

SHELL := /bin/bash
.DEFAULT_GOAL := help

# ─── Config ─────────────────────────────────────────────────────────────────

PYTHON_VERSION ?= 3.11
VENV_DIR       := .venv
VENV_BIN       := $(VENV_DIR)/bin
PYTHON         := $(VENV_BIN)/python
PIP            := $(VENV_BIN)/pip
UVICORN        := $(VENV_BIN)/uvicorn
NODE_DIR       := frontend/node_modules

BACKEND_PORT   ?= 8000
FRONTEND_PORT  ?= 3000

GCP_PROJECT    ?= marty-457112
GCR_REGISTRY   := gcr.io/$(GCP_PROJECT)

# ─── Safety ─────────────────────────────────────────────────────────────────

.PHONY: _check-pyenv _check-gcloud _check-kubectl

_check-pyenv:
	@command -v pyenv >/dev/null 2>&1 || { echo "Error: pyenv not installed"; exit 1; }
	@pyenv versions --bare | grep -q "^$(PYTHON_VERSION)" || { echo "Error: Python $(PYTHON_VERSION).x not in pyenv. Run: pyenv install $(PYTHON_VERSION)"; exit 1; }

_check-gcloud:
	@command -v gcloud >/dev/null 2>&1 || { echo "Error: gcloud CLI not installed"; exit 1; }
	@command -v docker >/dev/null 2>&1 || { echo "Error: docker not installed"; exit 1; }

_check-kubectl:
	@command -v kubectl >/dev/null 2>&1 || { echo "Error: kubectl not installed"; exit 1; }

# ─── Venv ───────────────────────────────────────────────────────────────────

$(VENV_DIR): _check-pyenv
	@echo "Creating Python $(PYTHON_VERSION) venv..."
	@PYENV_VERSION=$$(pyenv versions --bare | grep "^$(PYTHON_VERSION)" | tail -1) && \
		$$(pyenv prefix $$PYENV_VERSION)/bin/python -m venv $(VENV_DIR)
	@$(PIP) install --upgrade pip -q
	@echo "Venv ready."

# ─── Install ────────────────────────────────────────────────────────────────

.PHONY: install-backend install-services install-frontend setup

install-backend: $(VENV_DIR)
	@echo "Installing backend deps..."
	@$(PIP) install -r backend/requirements.txt -q

install-services: $(VENV_DIR)
	@for svc in services/agent-registry services/tool-registry services/document-registry; do \
		echo "Installing $$svc deps..."; \
		$(PIP) install -r $$svc/requirements.txt -q 2>/dev/null || true; \
	done

install-frontend:
	@echo "Installing frontend deps..."
	@cd frontend && npm install --silent

setup: install-backend install-services install-frontend
	@echo "Setup complete. Run 'make dev' to start."

# ─── Dev servers ────────────────────────────────────────────────────────────

.PHONY: dev dev-backend dev-frontend dev-agent-registry dev-tool-registry dev-document-registry

dev-backend: $(VENV_DIR)
	cd backend && PYTHONPATH=..:.:../shared $(UVICORN) main:app --host 0.0.0.0 --port $(BACKEND_PORT) --reload

dev-frontend: $(NODE_DIR)
	cd frontend && npx vite --port $(FRONTEND_PORT) --host

dev:
	@$(MAKE) dev-backend &
	@$(MAKE) dev-frontend
	@wait

dev-agent-registry: $(VENV_DIR)
	cd services/agent-registry && $(UVICORN) app:app --host 0.0.0.0 --port 8001 --reload

dev-tool-registry: $(VENV_DIR)
	cd services/tool-registry && $(UVICORN) app:app --host 0.0.0.0 --port 8002 --reload

dev-document-registry: $(VENV_DIR)
	cd services/document-registry && $(UVICORN) app:app --host 0.0.0.0 --port 8003 --reload

$(NODE_DIR):
	@cd frontend && npm install --silent

# ─── Testing ────────────────────────────────────────────────────────────────

.PHONY: test lint

test: $(VENV_DIR)
	PYTHONPATH=backend:shared $(PYTHON) test_civilization.py

lint: $(VENV_DIR)
	@$(PYTHON) -c "import ast, glob; [ast.parse(open(f).read()) or print(f'  {f}: OK') for f in glob.glob('backend/*.py') + glob.glob('shared/*.py') + glob.glob('services/*/app.py')]"

# ─── Deploy (full pipeline: build → push to GCR → apply K8s) ───────────────

.PHONY: deploy build push apply rollout

deploy: build push apply
	@echo ""
	@echo "Deploy complete → https://agents.london"

build: _check-gcloud
	@TAG=$$(date +'%y%m%d.%H%M%S') && echo $$TAG > .docker_tag && \
	echo "Building all images with tag $$TAG..." && \
	\
	docker build -t agent-registry:$$TAG -f services/agent-registry/Dockerfile . && \
	docker build -t tool-registry:$$TAG services/tool-registry && \
	docker build -t document-registry-service:$$TAG services/document-registry && \
	docker build -t agent-london-backend:$$TAG backend && \
	\
	if [ -f frontend/.env ]; then set -a; . frontend/.env; set +a; fi && \
	docker build \
		--build-arg VITE_GOOGLE_CLIENT_ID="$${VITE_GOOGLE_CLIENT_ID:-}" \
		--build-arg VITE_MS_CLIENT_ID="$${VITE_MS_CLIENT_ID:-}" \
		-t agent-london-frontend:$$TAG frontend && \
	\
	echo "All 5 images built: $$TAG"

push: _check-gcloud
	@TAG=$$(cat .docker_tag) && \
	echo "Pushing to $(GCR_REGISTRY) with tag $$TAG..." && \
	gcloud auth configure-docker gcr.io --quiet && \
	for img in agent-registry tool-registry document-registry-service agent-london-backend agent-london-frontend; do \
		docker tag $$img:$$TAG $(GCR_REGISTRY)/$$img:$$TAG && \
		docker tag $$img:$$TAG $(GCR_REGISTRY)/$$img:latest && \
		docker push $(GCR_REGISTRY)/$$img:$$TAG && \
		docker push $(GCR_REGISTRY)/$$img:latest && \
		echo "  $$img pushed."; \
	done && \
	echo "All images pushed."

apply: _check-kubectl
	@TAG=$$(cat .docker_tag) && \
	echo "Applying K8s manifests (tag $$TAG)..." && \
	for f in deploy/k8s/00-litellm-configmap.yaml \
	         deploy/k8s/01-agent-registry.yaml \
	         deploy/k8s/02-tool-registry.yaml \
	         deploy/k8s/03-backend.yaml \
	         deploy/k8s/04-frontend.yaml \
	         deploy/k8s/05-ingress.yaml \
	         deploy/k8s/06-document-registry.yaml; do \
		echo "  $$f"; \
		sed "s|:latest|:$$TAG|g" $$f | kubectl apply -f -; \
	done && \
	echo "Waiting for rollouts..." && \
	kubectl rollout status deployment/agent-registry --timeout=180s && \
	kubectl rollout status deployment/tool-registry --timeout=180s && \
	kubectl rollout status deployment/document-registry --timeout=180s && \
	kubectl rollout status deployment/agent-london-backend --timeout=180s && \
	kubectl rollout status deployment/agent-london-frontend --timeout=180s && \
	echo "" && \
	kubectl get ingress agents-london-ingress -n default 2>/dev/null || true

rollout: _check-kubectl
	kubectl rollout restart deployment/agent-registry deployment/tool-registry \
		deployment/document-registry deployment/agent-london-backend \
		deployment/agent-london-frontend -n default

# ─── Docker Compose (local) ────────────────────────────────────────────────

.PHONY: docker-up docker-down

docker-up:
	docker-compose up --build

docker-down:
	docker-compose down

# ─── Cleanup ────────────────────────────────────────────────────────────────

.PHONY: clean

clean:
	rm -rf $(VENV_DIR) frontend/node_modules frontend/dist .docker_tag
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	rm -rf .pytest_cache
	@echo "Clean."

# ─── Help ───────────────────────────────────────────────────────────────────

.PHONY: help

help:
	@echo ""
	@echo "  agents.london"
	@echo ""
	@echo "  Setup:"
	@echo "    make setup                 Create venv + install all deps"
	@echo ""
	@echo "  Dev:"
	@echo "    make dev                   Backend ($(BACKEND_PORT)) + Frontend ($(FRONTEND_PORT))"
	@echo "    make dev-backend           Backend only"
	@echo "    make dev-frontend          Frontend only"
	@echo "    make dev-agent-registry    Agent registry (8001)"
	@echo "    make dev-tool-registry     Tool registry (8002)"
	@echo "    make dev-document-registry Document registry (8003)"
	@echo ""
	@echo "  Test:"
	@echo "    make test                  Integration tests"
	@echo "    make lint                  Python syntax check"
	@echo ""
	@echo "  Deploy (local → GCR → GKE):"
	@echo "    make deploy                Build, push, apply (full pipeline)"
	@echo "    make build                 Build Docker images only"
	@echo "    make push                  Push to GCR only"
	@echo "    make apply                 Apply K8s manifests only"
	@echo "    make rollout               Restart all deployments"
	@echo ""
	@echo "  Docker Compose:"
	@echo "    make docker-up             docker-compose up --build"
	@echo "    make docker-down           docker-compose down"
	@echo ""
	@echo "  Cleanup:"
	@echo "    make clean                 Remove venv, node_modules, caches"
	@echo ""
