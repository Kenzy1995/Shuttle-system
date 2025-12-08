FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8080

# 安裝系統依賴（Pillow 會用到）
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential libjpeg62-turbo-dev zlib1g-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 請確認 server.py 就在專案根目錄（容器內 /app/server.py）
COPY . .

# 用 gunicorn 啟動，輸出存 stdout/stderr，Cloud Run 能收得到
CMD exec gunicorn \
    -k uvicorn.workers.UvicornWorker \
    --bind 0.0.0.0:${PORT} \
    --timeout 120 \
    --access-logfile '-' \
    --error-logfile '-' \
    server:app
