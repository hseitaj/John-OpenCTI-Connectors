# python:3.11.1-bullseye (Debian 11, end of life August 2026) no longer builds:
# its security archive is gone, so apt-get upgrade fails. Same layout as the
# other connectors now: current slim base, one apt layer, non-root user.
# Chromium was installed here but this connector never renders pages.
FROM python:3.11-slim-bookworm

# libmagic1: python-magic (a pycti dependency) loads it at import time.
RUN apt-get update && apt-get install -y --no-install-recommends libmagic1 \
    && rm -rf /var/lib/apt/lists/* \
    && adduser --disabled-password --gecos '' openphish

WORKDIR /home/openphish/

COPY src/requirements.txt /home/openphish/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY src/main.py src/client.py src/config.yml /home/openphish/src/

# Shared helpers from connectors/microservices (report classification).
# docker compose passes them as the "microservices" build context; a plain
# build needs: docker build --build-context microservices=../microservices .
COPY --from=microservices . /opt/shared/microservices
ENV PYTHONPATH="/opt/shared"

USER openphish
ENTRYPOINT ["python3", "/home/openphish/src/main.py"]
