FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    HERMES_HOME=/data/.hermes \
    PORT=9119 \
    RUN_MODE=both

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        bash \
        ca-certificates \
        curl \
        git \
        nodejs \
        npm \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /opt

RUN git clone --depth 1 https://github.com/NousResearch/hermes-agent.git /opt/hermes-agent \
    && python -m venv /opt/hermes-agent/venv \
    && /opt/hermes-agent/venv/bin/pip install --upgrade pip setuptools wheel \
    && /opt/hermes-agent/venv/bin/pip install -e "/opt/hermes-agent[web,mcp,cli,pty,slack,messaging]" \
    && cd /opt/hermes-agent/web \
    && npm ci \
    && npm run build

COPY . /opt/hermes-ax-plugin

RUN cd /opt/hermes-ax-plugin \
    && npm ci \
    && npm run build:only

COPY docker-entrypoint.sh /usr/local/bin/hermes-ax-entrypoint
RUN chmod +x /usr/local/bin/hermes-ax-entrypoint

VOLUME ["/data"]
EXPOSE 9119

CMD ["/usr/local/bin/hermes-ax-entrypoint"]
