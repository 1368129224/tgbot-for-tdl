# syntax=docker/dockerfile:1
FROM python:3.12-slim

# Optional: install curl to fetch tdl binary
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates curl \
  && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install python deps
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Install tdl (Linux x86_64) - version pin via build arg
ARG TDL_VERSION=0.16.0
RUN set -eux; \
  curl -fsSL -o /tmp/tdl.tar.gz "https://github.com/iyear/tdl/releases/download/v${TDL_VERSION}/tdl_${TDL_VERSION}_linux_amd64.tar.gz"; \
  tar -xzf /tmp/tdl.tar.gz -C /usr/local/bin tdl; \
  chmod +x /usr/local/bin/tdl; \
  rm -f /tmp/tdl.tar.gz

# Copy app
COPY tdl_bot ./tdl_bot
COPY app.py ./app.py

# Runtime: mount config + downloads
# - /data/tdl_bot_config.toml
# - /data/downloads
ENV TDL_BOT_CONFIG=/data/tdl_bot_config.toml

# Default command expects config file at /app/tdl_bot_config.toml (legacy)
# We'll recommend bind-mount to /app/tdl_bot_config.toml.
CMD ["python", "app.py"]
