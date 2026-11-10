FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    TZ=Europe/Istanbul \
    FABRIKA_HOME=/app

RUN apt-get update && apt-get install -y --no-install-recommends \
        ffmpeg fontconfig fonts-noto-core fonts-noto-cjk fonts-montserrat fonts-dejavu-core \
        ca-certificates tzdata \
    && rm -rf /var/lib/apt/lists/* && fc-cache -f

WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY fabrika ./fabrika

CMD ["python", "-m", "fabrika"]
