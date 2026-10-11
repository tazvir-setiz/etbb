FROM python:3.12-slim
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
RUN mkdir -p /data
COPY alembic.ini .
COPY migrations ./migrations
COPY app ./app
HEALTHCHECK --interval=30s --timeout=10s --retries=3 \
  CMD python -m app.main --check || exit 1
CMD ["python", "-m", "app.main"]
