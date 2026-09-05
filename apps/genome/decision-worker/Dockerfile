# Built from the REPOSITORY ROOT: the worker needs genome_core beside it AND
# shared/metering.py -- inference is metered into the platform consumption
# ledger (user directive 2026-09-05: every processing action in CU).
FROM python:3.12-slim
WORKDIR /srv
COPY apps/genome/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY apps/genome/core/ core/
COPY apps/genome/decision-worker/ decision-worker/
COPY shared/metering.py shared/metering.py
CMD ["python", "decision-worker/worker.py"]
