FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    HOST=0.0.0.0 \
    PORT=8080 \
    DOGFOOD_DATA=/data

WORKDIR /app
COPY app.py fixtures.json ./
COPY web ./web
COPY openapi.json ./

RUN groupadd --system fieldnote \
    && useradd --system --gid fieldnote --home-dir /app fieldnote \
    && mkdir -p /data \
    && chown fieldnote:fieldnote /data

USER fieldnote
EXPOSE 8080
HEALTHCHECK --interval=15s --timeout=3s --start-period=30s --retries=4 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/api/health', timeout=2)"
CMD ["python", "-u", "app.py"]
