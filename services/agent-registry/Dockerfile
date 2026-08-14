FROM python:3.11-slim

WORKDIR /app

# Built from the repository root, not from this directory: the registry
# executes pipelines and meters them, and those modules live in backend/.
# A service-scoped context cannot reach them, which is what made the image
# start with only app.py and fail on `import registry_api`.
#   docker build -f services/agent-registry/Dockerfile -t agent-registry .

COPY services/agent-registry/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY services/agent-registry/*.py ./
# One canonical copy of the shared runtime, not a vendored duplicate that
# drifts from the original.
COPY backend/metering.py backend/pipeline_runtime.py backend/embedding.py ./

EXPOSE 8001

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8001"]
