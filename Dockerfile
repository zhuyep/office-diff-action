FROM python:3.12-slim-bookworm

LABEL org.opencontainers.image.source="https://github.com/zhuyep/office-diff-action" \
      org.opencontainers.image.description="Visual review for changed Word and PowerPoint files" \
      org.opencontainers.image.licenses="MIT"

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        git \
        libreoffice-impress \
        libreoffice-writer \
        poppler-utils \
        fonts-dejavu-core \
        fonts-liberation \
        fonts-noto-cjk \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /opt/office-diff
COPY pyproject.toml README.md LICENSE ./
COPY src ./src
RUN pip install --no-cache-dir .

ENTRYPOINT ["office-diff"]
