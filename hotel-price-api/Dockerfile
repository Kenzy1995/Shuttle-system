# 原本
# FROM python:3.11-slim
# 或
# FROM mcr.microsoft.com/playwright/python:v1.42.0-jammy

# 改成這個（關鍵！）
FROM mcr.microsoft.com/playwright/python:v1.56.0-jammy

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV PYTHONUNBUFFERED=1
ENV PORT=8080

CMD ["gunicorn", "-k", "uvicorn.workers.UvicornWorker", "--bind", "0.0.0.0:8080", "--timeout", "300", "server:app"]
