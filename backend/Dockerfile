# GraphGuard API. Build context is ./backend
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    GRAPHGUARD_ENVIRONMENT=production \
    GRAPHGUARD_LOG_FORMAT=json \
    GRAPHGUARD_DATABASE_PATH=/data/graphguard.db

# Run as an ordinary user, not root
RUN useradd --uid 10001 --create-home --shell /usr/sbin/nologin app \
    && mkdir /data && chown app:app /data

WORKDIR /srv

# Dependencies first: this layer is cached until requirements.txt changes
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app

USER app
VOLUME /data
EXPOSE 8000

HEALTHCHECK --interval=15s --timeout=3s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/ready', timeout=2).status == 200 else 1)"

# ONE worker on purpose: the live stream, simulator and rate limiter keep state in memory
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
