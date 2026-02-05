FROM python:3.11-slim

WORKDIR /app

# Install system dependencies (redis-server for in-container sidecar test)
RUN apt-get update && apt-get install -y \
    gcc \
    redis-server \
    && rm -rf /var/lib/apt/lists/*

# Copy project root files needed for shared modules
COPY shared/ /app/shared/
COPY requirements.txt /app/

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy service-specific files
COPY services/shorten/ /app/services/shorten/

# Set working directory to service
WORKDIR /app/services/shorten

# Expose port
EXPOSE 8001

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8001/health')"

# Startup: boots Redis sidecar on loopback, then uvicorn
COPY services/shorten/start.sh /app/start.sh
RUN chmod +x /app/start.sh
CMD ["/app/start.sh"]
