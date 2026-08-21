# syntax=docker/dockerfile:1
FROM python:3.14-slim AS builder

ARG TARGETPLATFORM

WORKDIR /app

RUN if [ "$TARGETPLATFORM" = "linux/arm/v6" ]; then \
        apt-get update && \
        apt-get install -y --no-install-recommends \
            build-essential cmake python3-dev \
            libjpeg-dev zlib1g-dev libclang-dev && \
        rm -rf /var/lib/apt/lists/*; \
    fi

COPY requirements.txt .

RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --prefix=/install -r requirements.txt


FROM python:3.14-slim

ARG TARGETPLATFORM

ENV PYTHONUNBUFFERED=1

WORKDIR /app

RUN if [ "$TARGETPLATFORM" = "linux/arm/v6" ]; then \
        apt-get update && \
        apt-get install -y --no-install-recommends libjpeg62-turbo && \
        rm -rf /var/lib/apt/lists/*; \
    fi

COPY --from=builder /install /usr/local

COPY WEB_UI_VERSION .
COPY scripts/fetch_web_ui.py scripts/fetch_web_ui.py
RUN python scripts/fetch_web_ui.py

COPY . .

ENTRYPOINT ["python", "main.py"]
