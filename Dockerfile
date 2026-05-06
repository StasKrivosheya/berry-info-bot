FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY pyproject.toml README.md /app/
COPY src /app/src
COPY data/knowledge_base/parser_config.toml /app/data/knowledge_base/parser_config.toml
COPY data/knowledge_base/taxonomy.toml /app/data/knowledge_base/taxonomy.toml

RUN python -m pip install --upgrade pip \
    && pip install --no-cache-dir .

EXPOSE 8080

CMD ["python", "-m", "app.main"]
