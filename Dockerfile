# Multi-stage build for VideoScraper GCP Worker
# Stage 1: Build the Rust extension using Python base for compatibility
FROM python:3.11-slim as builder

# Install Rust and build dependencies
RUN apt-get update && apt-get install -y \
    curl \
    build-essential \
    pkg-config \
    libssl-dev \
    && rm -rf /var/lib/apt/lists/*

# Install Rust
RUN curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y
ENV PATH="/root/.cargo/bin:${PATH}"

# Install maturin
RUN pip install maturin

# Copy source
WORKDIR /app
COPY Cargo.toml Cargo.lock* ./
COPY src/ ./src/
COPY python/ ./python/
COPY pyproject.toml ./
COPY README.md ./

# Build the wheel (includes both Rust extension and Python modules)
RUN maturin build --release --no-default-features -o /wheels

# Stage 2: Runtime
FROM python:3.11-slim

# Install system dependencies including unzip for deno
RUN apt-get update && apt-get install -y \
    ffmpeg \
    curl \
    unzip \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Install Deno for yt-dlp JavaScript runtime support
RUN curl -fsSL https://deno.land/install.sh | sh
ENV DENO_INSTALL="/root/.deno"
ENV PATH="${DENO_INSTALL}/bin:${PATH}"

# Verify deno installation
RUN deno --version

WORKDIR /app

# Install Python dependencies
COPY deploy/gcp/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install yt-dlp for YouTube support
RUN pip install --no-cache-dir yt-dlp

# Copy and install the wheel (includes both Rust extension AND Python modules)
COPY --from=builder /wheels/*.whl /tmp/
RUN pip install /tmp/*.whl && rm -rf /tmp/*.whl

# Verify installation works
RUN python -c "from videoscraper import ScraperConfig; print('VideoScraper installed successfully')"

# Copy worker application ONLY (no python/ directory - it's in the wheel)
COPY deploy/gcp/worker.py .

# Set environment (NO PYTHONPATH - use installed package)
ENV PYTHONUNBUFFERED=1

# Configure yt-dlp to use deno
ENV YT_DLP_JS_RUNTIMES="deno"

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8080/health || exit 1

# Run the worker with gunicorn for production
CMD ["gunicorn", "--bind", "0.0.0.0:8080", "--workers", "1", "--threads", "8", "--timeout", "600", "worker:app"]
