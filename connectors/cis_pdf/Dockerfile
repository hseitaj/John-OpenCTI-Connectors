FROM python:3.12-slim

WORKDIR /opt/connector

RUN apt-get update \
  && apt-get install -y --no-install-recommends ca-certificates libmagic1 \
  && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY src/ ./src/
# The seed list must sit where CIS_SEED_FILE defaults (/opt/connector/seeds_urls.txt);
# only src/ was copied before, so every cycle logged "Seed file missing".
COPY seeds_urls.txt ./seeds_urls.txt

# Run the connector
CMD ["python", "-u", "/opt/connector/src/main.py"]
