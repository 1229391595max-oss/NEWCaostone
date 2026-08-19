FROM python:3.12.11-slim-bookworm@sha256:519591d6871b7bc437060736b9f7456b8731f1499a57e22e6c285135ae657bf7

ARG SOURCE_REVISION
ARG SOURCE_TREE_SHA
ARG IMAGE_INPUT_SHA256
ARG BUILD_CONTEXT_SHA256

LABEL org.opencontainers.image.title="NEWCaostone BizPulse Demo" \
      org.opencontainers.image.description="Pure-synthetic single-operator BizPulse Demo" \
      org.opencontainers.image.revision=$SOURCE_REVISION \
      org.opencontainers.image.bizpulse.source-tree-sha=$SOURCE_TREE_SHA \
      org.opencontainers.image.bizpulse.image-input-sha256=$IMAGE_INPUT_SHA256 \
      org.opencontainers.image.bizpulse.build-context-sha256=$BUILD_CONTEXT_SHA256 \
      org.opencontainers.image.source="local-only"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

RUN test -n "$SOURCE_REVISION" \
    && echo "$SOURCE_TREE_SHA" | grep -Eq '^[0-9a-f]{40}$' \
    && echo "$IMAGE_INPUT_SHA256" | grep -Eq '^[0-9a-f]{64}$' \
    && echo "$BUILD_CONTEXT_SHA256" | grep -Eq '^[0-9a-f]{64}$' \
    && groupadd --system --gid 10001 bizpulse \
    && useradd --system --uid 10001 --gid bizpulse --home-dir /app --shell /usr/sbin/nologin bizpulse

WORKDIR /app

COPY requirements.txt /app/requirements.txt
RUN python -m pip install --no-cache-dir --require-hashes --requirement /app/requirements.txt

COPY --chown=bizpulse:bizpulse alembic /app/alembic
COPY --chown=bizpulse:bizpulse alembic.ini /app/alembic.ini
COPY --chown=bizpulse:bizpulse api /app/api
COPY --chown=bizpulse:bizpulse frontend /app/frontend
COPY --chown=bizpulse:bizpulse src /app/src
COPY --chown=bizpulse:bizpulse scripts/seed_demo.py /app/scripts/seed_demo.py
COPY --chown=bizpulse:bizpulse scripts/prepare_cloud.py /app/scripts/prepare_cloud.py
COPY --chown=bizpulse:bizpulse scripts/maintain_sessions.py /app/scripts/maintain_sessions.py
COPY --chown=bizpulse:bizpulse scripts/maintain_storage.py /app/scripts/maintain_storage.py
COPY --chown=bizpulse:bizpulse scripts/phase1_fence_server.py /app/scripts/phase1_fence_server.py
COPY --chown=bizpulse:bizpulse scripts/rotate_operator_password.py /app/scripts/rotate_operator_password.py
COPY --chown=bizpulse:bizpulse tests/fixtures/synthetic/v1 /app/tests/fixtures/synthetic/v1

USER bizpulse
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
  CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health/live', timeout=3).read()"]

CMD ["python", "-m", "uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1", "--no-access-log"]
