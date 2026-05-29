FROM python:3.11-slim

ARG HERMES_AGENT_REF=a618789dbabf396a00fb061a491f54e12f536a45

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

RUN git init /opt/hermes-agent \
    && git -C /opt/hermes-agent remote add origin https://github.com/NousResearch/hermes-agent.git \
    && git -C /opt/hermes-agent fetch --depth 1 origin "${HERMES_AGENT_REF}" \
    && git -C /opt/hermes-agent checkout --detach FETCH_HEAD \
    && python -m venv /opt/hermes-agent/venv \
    && /opt/hermes-agent/venv/bin/pip install --upgrade pip setuptools wheel \
    && /opt/hermes-agent/venv/bin/pip install -e "/opt/hermes-agent[web,mcp,cli,pty,slack,messaging]" \
    && /opt/hermes-agent/venv/bin/pip install "notebooklm-py==0.5.0" \
    && cd /opt/hermes-agent/web \
    && npm ci \
    && npm run build

COPY scripts/patch_hermes_dashboard_public_api.py /tmp/patch_hermes_dashboard_public_api.py
RUN /opt/hermes-agent/venv/bin/python3 /tmp/patch_hermes_dashboard_public_api.py

COPY . /opt/hermes-ax-plugin

RUN cd /opt/hermes-ax-plugin \
    && npm ci \
    && npm run build:only

COPY docker-entrypoint.sh /usr/local/bin/hermes-ax-entrypoint
RUN chmod +x /usr/local/bin/hermes-ax-entrypoint

EXPOSE 9119

CMD ["/usr/local/bin/hermes-ax-entrypoint"]
