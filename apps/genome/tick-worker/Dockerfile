# Build from apps/genome context: the worker needs genome_core beside it.
FROM python:3.12-slim
WORKDIR /srv
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY core/ core/
COPY tick-worker/ tick-worker/
CMD ["python", "tick-worker/worker.py"]
