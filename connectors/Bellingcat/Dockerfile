# Playwright base image: ships a version-matched Chromium plus all browser
# system dependencies. This SUPERSEDES the project-standard python:3.11-slim
# base for this connector only (authorized override; see CONNECTOR_SCOPE.md).
# Keep the pip playwright version equal to the image tag below.
FROM mcr.microsoft.com/playwright/python:v1.49.0-jammy

# libmagic1 before pip: still required (python-magic, a pycti dependency,
# imports the native library at import time). This standing rule is NOT
# superseded by the base-image override.
RUN apt-get update && apt-get install -y --no-install-recommends \
    libmagic1 && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Browsers are present in the base image; this is a belt-and-suspenders ensure.
RUN playwright install chromium

COPY . .
# Shared helpers from connectors/microservices (PDF rendering, report
# classification). docker compose passes them as the "microservices" build
# context; a plain build needs: docker build --build-context microservices=../microservices .
COPY --from=microservices . /opt/shared/microservices
ENV PYTHONPATH="/opt/shared"

CMD ["python", "main.py"]
