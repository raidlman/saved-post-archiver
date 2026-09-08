ARG PYTHON_VERSION=3.14
ARG APP_VERSION=0.1.0

FROM python:${PYTHON_VERSION}-slim

ARG APP_VERSION
ENV APP_VERSION=${APP_VERSION} \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# ffmpeg: yt-dlp needs it to mux v.redd.it's separate video/audio streams.
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml ./
COPY src ./src
RUN pip install --upgrade pip && pip install -e .

RUN useradd -u 1000 -m archiver
USER 1000

ENTRYPOINT ["python", "-m", "reddit_archiver"]
