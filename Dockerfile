FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY scripts ./scripts
COPY sample_data ./sample_data

# Roda sem root dentro do container
RUN useradd --create-home appuser
USER appuser

# O Railway define PORT automaticamente. --proxy-headers faz o IP real do
# visitante chegar na aplicação (usado no limite de requisições por IP).
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --proxy-headers --forwarded-allow-ips='*'"]
