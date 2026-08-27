FROM python:3.11-slim

WORKDIR /app

# Built from the repository root, not from this directory: the registry meters
# ingestion and retrieval, and that module lives in backend/. A service-scoped
# build context cannot reach it.
#   docker build -f services/document-registry/Dockerfile -t document-registry .

COPY services/document-registry/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY services/document-registry/*.py ./
# One canonical copy of the shared meter, not a vendored duplicate that drifts.
COPY shared/metering.py ./

EXPOSE 8003

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8003"]
