#!/bin/bash
# 授予 Firebase 權限腳本

set -e

PROJECT_ID="shuttle-system-487204"
SERVICE_ACCOUNT="shuttle-system@${PROJECT_ID}.iam.gserviceaccount.com"

echo "🔐 開始授予 Firebase 權限..."
echo "專案 ID: ${PROJECT_ID}"
echo "服務帳號: ${SERVICE_ACCOUNT}"
echo ""

# 設置專案
echo "📌 設置 GCP 專案..."
gcloud config set project ${PROJECT_ID}

# 授予 Firebase Admin 權限
echo "🔑 授予 Firebase Admin 權限..."
gcloud projects add-iam-policy-binding ${PROJECT_ID} \
  --member="serviceAccount:${SERVICE_ACCOUNT}" \
  --role="roles/firebase.admin" \
  --condition=None

# 授予 Datastore User 權限（如果需要）
echo "🔑 授予 Datastore User 權限..."
gcloud projects add-iam-policy-binding ${PROJECT_ID} \
  --member="serviceAccount:${SERVICE_ACCOUNT}" \
  --role="roles/datastore.user" \
  --condition=None

# 驗證權限
echo ""
echo "✅ 驗證已授予的權限..."
gcloud projects get-iam-policy ${PROJECT_ID} \
  --flatten="bindings[].members" \
  --filter="bindings.members:serviceAccount:${SERVICE_ACCOUNT}" \
  --format="table(bindings.role)"

echo ""
echo "✅ 權限授予完成！"
echo ""
echo "⚠️  注意：您還需要在 Firebase Console 中更新 Realtime Database 規則："
echo "   https://console.firebase.google.com/project/shuttle-system-60d6a/database/shuttle-system-60d6a-default-rtdb/rules"
echo ""
echo "   建議規則："
echo "   {"
echo "     \"rules\": {"
echo "       \"booking_seq\": {"
echo "         \".read\": \"auth != null\","
echo "         \".write\": \"auth != null\""
echo "       },"
echo "       \"cap_lock\": {"
echo "         \".read\": \"auth != null\","
echo "         \".write\": \"auth != null\""
echo "       }"
echo "     }"
echo "   }"

