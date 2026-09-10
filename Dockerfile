FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements and install
COPY sterilespace/requirements.txt requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Copy project files
COPY . .

# Set default port
ENV PORT=8000
EXPOSE 8000

# Start FastAPI server
CMD ["sh", "-c", "uvicorn server.app:app --app-dir sterilespace --host 0.0.0.0 --port ${PORT:-8000}"]
