#!/bin/bash
# 重建構所有服務的腳本
# 確保服務網址不會改變

set -e

PROJECT_ID="forte-booking-system"
REGION="asia-east1"

echo "=========================================="
echo "開始重建構所有服務"
echo "專案: $PROJECT_ID"
echo "區域: $REGION"
echo "=========================================="

# 記錄當前服務網址
echo ""
echo "📋 當前服務網址："
gcloud run services list --region=$REGION --project=$PROJECT_ID --format="table(metadata.name,status.url)"

echo ""
echo "✅ 重建構不會改變這些網址"
echo ""

# 1. 重建構 hotel-web (前端)
echo "=========================================="
echo "1. 重建構 hotel-web (前端)"
echo "=========================================="
cd web
gcloud auth configure-docker asia-east1-docker.pkg.dev --quiet
echo "建構 Docker 映像..."
gcloud builds submit --tag asia-east1-docker.pkg.dev/$PROJECT_ID/hotel-web/web --project=$PROJECT_ID
echo "部署到 Cloud Run..."
gcloud run deploy hotel-web \
  --image=asia-east1-docker.pkg.dev/$PROJECT_ID/hotel-web/web \
  --region=$REGION \
  --platform=managed \
  --allow-unauthenticated \
  --service-account=forte-booking-system@forte-booking-system.iam.gserviceaccount.com \
  --port=8080 \
  --project=$PROJECT_ID
cd ..

# 2. 重建構 booking-api
echo ""
echo "=========================================="
echo "2. 重建構 booking-api"
echo "=========================================="
cd booking-api
gcloud auth configure-docker gcr.io --quiet
echo "建構 Docker 映像..."
gcloud builds submit --tag gcr.io/$PROJECT_ID/booking-api --project=$PROJECT_ID
echo "部署到 Cloud Run..."
gcloud run deploy booking-api \
  --image=gcr.io/$PROJECT_ID/booking-api \
  --region=$REGION \
  --platform=managed \
  --allow-unauthenticated \
  --service-account=forte-booking-system@forte-booking-system.iam.gserviceaccount.com \
  --memory=2Gi \
  --cpu=2 \
  --max-instances=10 \
  --timeout=300s \
  --project=$PROJECT_ID
cd ..

# 3. 重建構 booking-manager
echo ""
echo "=========================================="
echo "3. 重建構 booking-manager"
echo "=========================================="
cd booking-manager
gcloud auth configure-docker gcr.io --quiet
echo "建構 Docker 映像..."
gcloud builds submit --tag gcr.io/$PROJECT_ID/booking-manager --project=$PROJECT_ID
echo "部署到 Cloud Run..."
gcloud run deploy booking-manager \
  --image=gcr.io/$PROJECT_ID/booking-manager \
  --region=$REGION \
  --platform=managed \
  --allow-unauthenticated \
  --service-account=forte-booking-system@forte-booking-system.iam.gserviceaccount.com \
  --memory=2Gi \
  --cpu=2 \
  --max-instances=10 \
  --timeout=300s \
  --project=$PROJECT_ID
cd ..

# 4. 重建構 driver-api2
echo ""
echo "=========================================="
echo "4. 重建構 driver-api2"
echo "=========================================="
cd driver-api2
gcloud auth configure-docker gcr.io --quiet
echo "建構 Docker 映像..."
gcloud builds submit --tag gcr.io/$PROJECT_ID/driver-api2 --project=$PROJECT_ID
echo "部署到 Cloud Run..."
gcloud run deploy driver-api2 \
  --image=gcr.io/$PROJECT_ID/driver-api2 \
  --region=$REGION \
  --platform=managed \
  --allow-unauthenticated \
  --service-account=forte-booking-system@forte-booking-system.iam.gserviceaccount.com \
  --memory=1Gi \
  --cpu=1 \
  --max-instances=5 \
  --timeout=120s \
  --project=$PROJECT_ID
cd ..

echo ""
echo "=========================================="
echo "✅ 所有服務重建構完成"
echo "=========================================="
echo ""
echo "📋 驗證服務網址（應該沒有改變）："
gcloud run services list --region=$REGION --project=$PROJECT_ID --format="table(metadata.name,status.url)"

