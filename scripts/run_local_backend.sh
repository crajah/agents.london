#!/usr/bin/env bash
# ==============================================================================
# Run agent.london Backend Locally with Local Redis & PostgreSQL
# ==============================================================================
set -e

echo "🚀 Starting agent.london backend locally..."

# 1. Check if local Redis is running on port 6379, or start container if needed
if nc -z 127.0.0.1 6379 2>/dev/null; then
  echo "✅ Local Redis detected running on 127.0.0.1:6379"
else
  echo "⚠️ Local Redis not detected on port 6379."
  if command -v docker >/dev/null 2>&1; then
    echo "🐳 Launching local Redis container via Docker..."
    docker run -d --name local-redis-agent-london -p 6379:6379 redis:alpine 2>/dev/null || docker start local-redis-agent-london
    echo "✅ Local Redis Docker container active on 127.0.0.1:6379"
  else
    echo "⚠️ Docker not found. Proceeding with in-memory bus fallback."
  fi
fi

# 2. Check if local PostgreSQL is running on port 5432, or start container if needed
if nc -z 127.0.0.1 5432 2>/dev/null; then
  echo "✅ Local PostgreSQL detected running on 127.0.0.1:5432"
else
  echo "⚠️ Local PostgreSQL not detected on port 5432."
  if command -v docker >/dev/null 2>&1; then
    echo "🐳 Launching local PostgreSQL container via Docker..."
    docker run -d --name local-postgres-agent-london -e POSTGRES_PASSWORD=postgrespassword -e POSTGRES_USER=crajah -e POSTGRES_DB=postgres -p 5432:5432 postgres:15-alpine 2>/dev/null || docker start local-postgres-agent-london
    echo "✅ Local PostgreSQL Docker container active on 127.0.0.1:5432"
  fi
fi

# 3. Export local environment variables
export REDIS_HOST="127.0.0.1"
export REDIS_PORT="6379"
export POSTGRES_HOST="127.0.0.1"
export POSTGRES_PORT="5432"
export POSTGRES_USER="crajah"
export POSTGRES_PASSWORD="postgrespassword"
export POSTGRES_DB="postgres"
export POSTGRES_URI="${POSTGRES_URI:-postgresql://crajah:postgrespassword@127.0.0.1:5432/postgres}"
export AGENT_REGISTRY_URL="http://localhost:8001"
export TOOL_REGISTRY_URL="http://localhost:8002"
export OPENAI_API_BASE="http://localhost:4000/v1"
export OPENAI_API_KEY="BEVZ-6L81-OZ8Y"

echo "🌐 Environment configured:"
echo "   - REDIS_HOST: ${REDIS_HOST}:${REDIS_PORT}"
echo "   - POSTGRES_URI: ${POSTGRES_URI}"
echo "   - OPENAI_API_BASE: ${OPENAI_API_BASE}"

# 4. Launch Uvicorn FastAPI server on port 8000
echo "🔥 Starting Uvicorn server on http://localhost:8000..."
uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000
