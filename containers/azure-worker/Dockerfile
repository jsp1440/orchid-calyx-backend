# syntax=docker/dockerfile:1.7
FROM python:3.12.15-alpine3.24@sha256:1b668429b3511ab407d8e00648891631b0b1a4d7e15e3ca70f38ab5b91ad4ab4 AS dependencies
ENV PIP_DISABLE_PIP_VERSION_CHECK=1 PIP_NO_CACHE_DIR=1
COPY containers/azure-worker/requirements.lock /build/requirements.lock
RUN python -m pip install --require-hashes --only-binary=:all: --no-compile \
    --prefix=/install -r /build/requirements.lock

FROM python:3.12.15-alpine3.24@sha256:1b668429b3511ab407d8e00648891631b0b1a4d7e15e3ca70f38ab5b91ad4ab4
ARG SOURCE_REVISION
LABEL org.opencontainers.image.source="https://github.com/jsp1440/orchid-calyx-backend" \
      org.opencontainers.image.revision="${SOURCE_REVISION}" \
      org.opencontainers.image.title="Governed Calyx Azure worker"
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PYTHONPATH=/opt/calyx \
    CALYX_AZURE_WORKER_ENABLED=false CALYX_AZURE_ENABLED=false HOME=/tmp
COPY --from=dependencies /install /usr/local
WORKDIR /opt/calyx
COPY app/calyx_orchestrator/__init__.py ./app/calyx_orchestrator/__init__.py
COPY app/calyx_orchestrator/engineering_core.py \
     app/calyx_orchestrator/executor.py \
     app/calyx_orchestrator/azure_execution_contract.py \
     app/calyx_orchestrator/azure_worker.py ./app/calyx_orchestrator/
USER 65532:65532
STOPSIGNAL SIGTERM
ENTRYPOINT ["python", "-m", "app.calyx_orchestrator.azure_worker"]
