# Multi-stage build for VideoScraper GCP Worker
FROM rust:1.75-slim as rust-builder

# Install build dependencies
RUN apt-get update && apt-get install -y \
    python3-dev \
    python3-pip \
    pkg-config \
    libssl-dev \
    && rm -rf /var/lib/apt/lists/*

# Install maturin
RUN pip3 install maturin --break-system-packages

# Copy source
WORKDIR /app
COPY Cargo.toml Cargo.lock* ./
COPY src/ ./src/
COPY python/ ./python/
COPY pyproject.toml ./

# Build the Rust extension
RUN maturin build --release --no-default-features

# Python runtime stage
FROM python:3.11-slim

# Install system dependencies
RUN apt-get update && apt-get install -y \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python dependencies
COPY deploy/gcp/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install yt-dlp for YouTube support
RUN pip install --no-cache-dir yt-dlp

# Copy wheel from builder and install
COPY --from=rust-builder /app/target/wheels/*.whl /tmp/
RUN pip install /tmp/*.whl && rm /tmp/*.whl

# Copy application code
COPY python/ ./python/
COPY deploy/gcp/worker.py .

# Set environment
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app/python

# Run the worker
CMD ["python", "worker.py"]

