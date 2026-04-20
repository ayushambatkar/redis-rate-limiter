FROM python:3.11-slim

WORKDIR /app

# Install Redis
RUN apt-get update && apt-get install -y redis-server && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Start Redis + FastAPI
CMD redis-server --daemonize yes && \
    uvicorn app.main:app --host 0.0.0.0 --port 8000