# Polymarket MCP Server - Production Dockerfile
# Multi-stage build for minimal image size and security

# Stage 1: Builder - Build Python wheel
FROM python:3.12-slim as builder

WORKDIR /build

# Install build dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Copy project files
COPY pyproject.toml README.md ./
COPY src/ ./src/

# Build wheel
RUN pip install --no-cache-dir build && \
    python -m build --wheel

# Stage 2: Runtime - Minimal production image
FROM python:3.12-slim

# Create non-root user for security
RUN groupadd -r polymarket && \
    useradd -r -g polymarket -u 1000 polymarket && \
    mkdir -p /app/logs && \
    chown -R polymarket:polymarket /app

WORKDIR /app

# Install runtime dependencies only
COPY --from=builder /build/dist/*.whl .
RUN pip install --no-cache-dir *.whl && \
    rm -f *.whl && \
    pip cache purge

# Copy source code (needed for imports)
COPY --chown=polymarket:polymarket src/ ./src/

# Switch to non-root user
USER polymarket

# Environment variables
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    LOG_LEVEL=INFO

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import sys; sys.exit(0)"

# Expose stdio interface for MCP
# Note: MCP servers communicate via stdio, not HTTP ports

# Entry point
CMD ["python", "-m", "polymarket_mcp.server"]

# Labels for metadata. VERSION comes from the build-arg the release workflow
# passes, so it does not drift from __init__.py.
ARG VERSION=dev
LABEL org.opencontainers.image.title="Polymarket MCP Server" \
      org.opencontainers.image.description="Model Context Protocol server for Polymarket trading" \
      org.opencontainers.image.version="${VERSION}" \
      org.opencontainers.image.authors="Polymarket MCP Team" \
      org.opencontainers.image.licenses="MIT"
