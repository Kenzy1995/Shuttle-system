FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8080

# 安裝 Playwright 所需系統套件
RUN apt-get update && apt-get install -y \
    wget \
    gnupg \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# 安裝 Python 套件 + 安裝瀏覽器
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt && \
    playwright install --with-deps chromium

# 複製程式碼
COPY . .

CMD ["gunicorn",
     "-k", "uvicorn.workers.UvicornWorker",
     "--bind", "0.0.0.0:8080",
     "--timeout", "300",
     "server:app"]
