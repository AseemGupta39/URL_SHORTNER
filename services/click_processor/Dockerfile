FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Copy project root files needed for shared modules
COPY shared/ /app/shared/
COPY requirements.txt /app/

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy batch_processor for click_worker.py (shared worker code)
COPY services/batch_processor/ /app/services/batch_processor/

# Copy service-specific files
COPY services/click_processor/ /app/services/click_processor/

# Set working directory to service
WORKDIR /app/services/click_processor

# Expose port
EXPOSE 8004

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8004/health')"

# Run the service
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8004"]
