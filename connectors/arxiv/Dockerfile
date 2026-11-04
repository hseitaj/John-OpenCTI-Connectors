# Project-standard base. Unlike the Bellingcat / ScienceDaily / DFIR connectors,
# arXiv needs NO browser: it fetches the paper's existing PDF directly, so there
# is no Playwright/Chromium stack and the canonical python:3.11-slim base applies.
FROM python:3.11-slim

# libmagic1 before pip: python-magic (a pycti dependency) imports the native
# library at import time, so it must be present before the pip install.
RUN apt-get update && apt-get install -y --no-install-recommends \
    libmagic1 && rm -rf /var/lib/apt/lists/*

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
