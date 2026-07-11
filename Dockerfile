# syntax=docker/dockerfile:1

# Retrieve — eval-driven retrieval architecture selection
# Multi-stage build: frontend + backend

# Stage 1: Build SvelteKit frontend
FROM node:22-slim AS frontend-build
WORKDIR /app
COPY package.json package-lock.json* ./
RUN npm ci --ignore-scripts
COPY . .
RUN npm run build

# Stage 2: Python backend + built frontend
FROM python:3.11-slim AS runtime

# Install system dependencies
RUN apt-get update && \
    apt-get install -y --no-install-recommends curl && \
    rm -rf /var/lib/apt/lists/*

# Install Azure CLI (needed for az bicep, az ml)
RUN curl -sL https://aka.ms/InstallAzureCLIDeb | bash

WORKDIR /app

# Install Python dependencies
COPY retrieve-core/pyproject.toml retrieve-core/
COPY retrieve-core/src/ retrieve-core/src/
RUN pip install --no-cache-dir ./retrieve-core

# Copy built frontend
COPY --from=frontend-build /app/build/ /app/build/

# Copy corpus and config (if present)
COPY corpus/ /app/corpus/
COPY retrieve.yaml* /app/

# Runtime configuration
ENV HOST=0.0.0.0
ENV PORT=8000
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8000/api/health || exit 1

# Run the web UI
CMD ["retrieve", "ui", "--host", "0.0.0.0", "--port", "8000"]
