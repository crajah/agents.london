FROM python:3.11-slim

WORKDIR /app

# Built from the REPOSITORY ROOT, not from backend/. The shared modules
# (metering, embedding, pipeline_runtime) live in shared/ because all three
# registry services import them too, so this image has to reach outside its own
# directory to get them. The CI build context was widened to match; building
# this Dockerfile with a narrower context will fail on the shared/ COPY.
COPY apps/civilization/backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY apps/civilization/backend/ /app/backend/
COPY shared/*.py /app/shared/

# backend is imported as a package (`from backend.registry_contract import …`)
# while the shared modules are imported flat (`from metering import …`), which
# is why all three roots are on the path.
ENV PYTHONPATH=/app:/app/backend:/app/shared

EXPOSE 8000

CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000"]
