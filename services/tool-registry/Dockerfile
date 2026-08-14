FROM python:3.11-slim

WORKDIR /app

# Built from the repository root, not from this directory: the registry meters
# tool calls and embeds tool descriptions, and those modules live in backend/.
# A service-scoped build context cannot reach them.
#   docker build -f services/tool-registry/Dockerfile -t tool-registry .

COPY services/tool-registry/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY services/tool-registry/*.py ./
# One canonical copy of the shared runtime, not a vendored duplicate that
# drifts from the original.
COPY backend/metering.py backend/embedding.py ./

EXPOSE 8002

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8002"]
