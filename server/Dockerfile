# Rainman sync server — stdlib only, no pip install step (zero deps).
# The base image is the only external artifact; pre-load it for air-gapped use.
FROM python:3.12-slim

WORKDIR /app
COPY rainman_server ./rainman_server
COPY pyproject.toml README.md ./

# Memory + tokens live on a mounted volume so they survive container restarts.
VOLUME ["/data"]
EXPOSE 8787

# Runs plain HTTP; terminate TLS at a reverse proxy in front (see DEPLOY.md).
ENTRYPOINT ["python", "-m", "rainman_server", "serve", \
            "--host", "0.0.0.0", "--port", "8787", "--db", "/data/rainman-sync.db"]
