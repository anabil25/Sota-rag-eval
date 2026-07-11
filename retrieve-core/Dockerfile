FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8000

WORKDIR /app

COPY pyproject.toml ./
COPY src ./src

RUN pip install --no-cache-dir ".[graphrag]"

EXPOSE 8000

CMD ["uvicorn", "retrieve.graphrag_worker.app:app", "--host", "0.0.0.0", "--port", "8000"]
