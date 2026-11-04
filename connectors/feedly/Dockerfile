FROM python:3.12-slim-bookworm
ENV DEBIAN_FRONTEND=noninteractive
WORKDIR /opt/opencti-feedly-connector
RUN apt-get update && apt-get install -y --no-install-recommends \
    libmagic1 git ca-certificates \
    fontconfig \
    libpango-1.0-0 \
    libpangoft2-1.0-0 \
    libgdk-pixbuf2.0-0 \
    libffi-dev \
    shared-mime-info \
    libcairo2 \
 && rm -rf /var/lib/apt/lists/*
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
ENV PYTHONUNBUFFERED=1
# Shared helpers from connectors/microservices (PDF rendering, report
# classification). docker compose passes them as the "microservices" build
# context; a plain build needs: docker build --build-context microservices=../microservices .
COPY --from=microservices . /opt/shared/microservices
ENV PYTHONPATH="/opt/shared"

ENTRYPOINT ["python", "-u", "main.py"]
