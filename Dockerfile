FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/app/src \
    TZ=Asia/Kolkata

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# .dockerignore keeps .env, keys, databases and logs out of the image
COPY src ./src
RUN useradd --create-home axon && mkdir -p /app/data /app/reports && chown -R axon /app
USER axon

# Finding 14: unhealthy when the trading loop stops
HEALTHCHECK --interval=2m --timeout=20s --start-period=2m --retries=2 \
    CMD python -m axon health || exit 1

CMD ["python", "-m", "axon", "run"]
