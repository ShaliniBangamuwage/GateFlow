FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir --timeout 180 --retries 10 --requirement requirements.txt
COPY app ./app
COPY scripts ./scripts

RUN useradd --create-home --uid 10001 app
RUN mkdir -p /app/models && chown -R app:app /app/models
USER app

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
