.PHONY: all build build-release dev install test lint clean docs

# Default target
all: build

# Build in debug mode
build:
	cargo build
	maturin develop

# Build in release mode
build-release:
	cargo build --release
	maturin develop --release

# Development mode (faster builds, debug symbols)
dev:
	maturin develop

# Install to current Python environment
install: build-release
	pip install .

# Build wheel for distribution
wheel:
	maturin build --release

# Run Rust tests
test-rust:
	cargo test

# Run Python tests
test-python:
	python -m pytest tests/ -v

# Run all tests
test: test-rust test-python

# Lint Rust code
lint-rust:
	cargo clippy -- -D warnings
	cargo fmt --check

# Lint Python code
lint-python:
	python -m ruff check python/
	python -m ruff format --check python/

# Lint all code
lint: lint-rust lint-python

# Format code
format:
	cargo fmt
	python -m ruff format python/

# Clean build artifacts
clean:
	cargo clean
	rm -rf target/
	rm -rf dist/
	rm -rf *.egg-info/
	rm -rf .pytest_cache/
	rm -rf python/videoscraper/*.so
	rm -rf python/videoscraper/__pycache__/
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete 2>/dev/null || true

# Generate documentation
docs:
	cargo doc --no-deps --open

# Run a quick benchmark
bench:
	cargo bench

# Check for updates
update:
	cargo update
	pip install --upgrade maturin

# Show project info
info:
	@echo "VideoScraper - High-performance video scraping infrastructure"
	@echo ""
	@echo "Rust version:"
	@rustc --version
	@echo ""
	@echo "Python version:"
	@python --version
	@echo ""
	@echo "Maturin version:"
	@maturin --version

# Development setup
setup:
	pip install maturin pytest pytest-asyncio ruff
	cargo fetch

# Run example
example:
	@echo "Running simple download example..."
	python examples/simple_download.py

# Help
help:
	@echo "VideoScraper Makefile"
	@echo ""
	@echo "Usage: make [target]"
	@echo ""
	@echo "Targets:"
	@echo "  build         Build in debug mode"
	@echo "  build-release Build in release mode (optimized)"
	@echo "  dev           Development mode (fast builds)"
	@echo "  install       Install to Python environment"
	@echo "  wheel         Build distributable wheel"
	@echo "  test          Run all tests"
	@echo "  test-rust     Run Rust tests only"
	@echo "  test-python   Run Python tests only"
	@echo "  lint          Lint all code"
	@echo "  format        Format all code"
	@echo "  clean         Clean build artifacts"
	@echo "  docs          Generate documentation"
	@echo "  setup         Setup development environment"
	@echo "  example       Run example script"
	@echo "  help          Show this help message"

