# Dockerfile for KernelWorx Backend (Python 3.14)
# Use a pinned official uv image for installation
FROM ghcr.io/astral-sh/uv:0.4.22 AS uv
FROM python:3.14-slim

# Install uv from official pinned image
COPY --from=uv /uv /bin/uv
RUN ln -s /bin/uv /bin/uvx

# Set working directory
WORKDIR /app

# Copy dependency files
COPY pyproject.toml uv.lock ./

# Install dependencies (without dev)
RUN uv sync --locked --no-dev

# Copy application source
COPY src/ ./src/

# Set environment variables
ENV PYTHONPATH=/app/src
ENV PYTHONUNBUFFERED=1
ENV PATH="/app/.venv/bin:${PATH}"

# Run the application (placeholder - update for your actual entrypoint)
CMD ["uv", "run", "python", "-m", "src.main"]
