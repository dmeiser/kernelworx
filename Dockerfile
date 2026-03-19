# Dockerfile for KernelWorx Backend (Python 3.14)
FROM python:3.14-slim

# Install uv
COPY --from=astral-sh/setup-uv:latest /uv /uvx /bin/

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

# Run the application (placeholder - update for your actual entrypoint)
# CMD ["uv", "run", "python", "-m", "src.main"]
