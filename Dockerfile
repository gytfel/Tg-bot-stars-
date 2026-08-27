FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    DB_PATH=/data/shop.db

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# база лежит в томе, процесс работает не от root
RUN mkdir -p /data && useradd --system --home /app shopbot && chown -R shopbot /app /data
USER shopbot
VOLUME ["/data"]

# webhook-режим слушает этот порт; для polling он просто не используется
EXPOSE 8080

HEALTHCHECK --interval=60s --timeout=10s --start-period=15s --retries=3 \
    CMD python doctor.py --health || exit 1

CMD ["python", "bot.py"]
