FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /opt/connector

RUN apt-get update \
  && apt-get install -y --no-install-recommends ca-certificates libmagic1 \
  && rm -rf /var/lib/apt/lists/*

COPY requirements.txt /opt/connector/requirements.txt
RUN pip install --no-cache-dir -r /opt/connector/requirements.txt

COPY src/ /opt/connector/src/

ENV PYTHONPATH="/opt/connector/src"

# Shared helpers from connectors/microservices (PDF rendering, report
# classification). docker compose passes them as the "microservices" build
# context; a plain build needs: docker build --build-context microservices=../microservices .
COPY --from=microservices . /opt/shared/microservices
ENV PYTHONPATH="/opt/shared:/opt/connector/src"

CMD ["python", "-u", "/opt/connector/src/connector.py"]
