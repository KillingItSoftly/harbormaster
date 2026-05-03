FROM python:3.12-slim

WORKDIR /app

# Install dependencies first to cache the layer
COPY pyproject.toml ./
COPY src/ ./src/
RUN pip install --no-cache-dir .

# Run as non-root
RUN useradd -m -u 1000 bot
USER bot

# config.yaml path or HARBORMASTER_CONFIG_YAML inline secret env var
ENV HARBORMASTER_CONFIG=/app/config/config.yaml \
    PYTHONUNBUFFERED=1

CMD ["python", "-m", "harbormaster_bot"]
