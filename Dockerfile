# Axon Capital Engine - Scheduler Container
# Builds a lightweight image that runs the trading scheduler

FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    TZ=Asia/Kolkata

# Set workdir
WORKDIR /app

# Install system deps (for some Python packages like psycopg2-binary)
RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Copy project code (.dockerignore keeps .env, keys, logs and local DBs out)
COPY . .
RUN mkdir -p /app/logs

# Default command: run the scheduler in mock/live mode as configured
CMD ["python", "run_trader.py", "--schedule"]
