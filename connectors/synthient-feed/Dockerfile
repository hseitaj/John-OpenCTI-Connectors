FROM python:3.11-slim

# libmagic1 is required by pycti via python-magic
RUN apt-get update && apt-get install -y --no-install-recommends \
    libmagic1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY connector.py .

# Shared helpers from connectors/microservices (PDF rendering, report
# classification). docker compose passes them as the "microservices" build
# context; a plain build needs: docker build --build-context microservices=../microservices .
COPY --from=microservices . /opt/shared/microservices
ENV PYTHONPATH="/opt/shared"

CMD ["python", "connector.py"]
