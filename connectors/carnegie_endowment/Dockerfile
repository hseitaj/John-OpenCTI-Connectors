FROM python:3.11-slim-bookworm

RUN apt-get update && apt-get install -y --no-install-recommends \
    libmagic1 libpango-1.0-0 libpangocairo-1.0-0 \
    libgdk-pixbuf-2.0-0 libcairo2 libffi-dev \
    shared-mime-info fonts-liberation \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
# Shared helpers from connectors/microservices (PDF rendering, report
# classification). docker compose passes them as the "microservices" build
# context; a plain build needs: docker build --build-context microservices=../microservices .
COPY --from=microservices . /opt/shared/microservices
ENV PYTHONPATH="/opt/shared"

CMD ["python", "main.py"]
