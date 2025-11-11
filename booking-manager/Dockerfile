FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
EXPOSE 8080
ENV PORT=8080
CMD exec gunicorn -k uvicorn.workers.UvicornWorker server:app --bind 0.0.0.0:$PORT
