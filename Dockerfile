FROM python:3.12-slim

LABEL org.opencontainers.image.source="https://github.com/cracketus/senior-pomidor-server"

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

COPY app ./app
COPY pyproject.toml README.md ./
RUN pip install --no-cache-dir -e .

COPY alembic.ini ./
COPY migrations ./migrations
COPY config/state_estimator_v1.yaml ./config/state_estimator_v1.yaml

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
