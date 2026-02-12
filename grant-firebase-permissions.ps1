# PowerShell 腳本：授予 Firebase 權限

$PROJECT_ID = "shuttle-system-487204"
$SERVICE_ACCOUNT = "shuttle-system@${PROJECT_ID}.iam.gserviceaccount.com"

Write-Host "🔐 開始授予 Firebase 權限..." -ForegroundColor Cyan
Write-Host "專案 ID: $PROJECT_ID"
Write-Host "服務帳號: $SERVICE_ACCOUNT"
Write-Host ""

# 設置專案
Write-Host "📌 設置 GCP 專案..." -ForegroundColor Yellow
gcloud config set project $PROJECT_ID

# 授予 Firebase Admin 權限
Write-Host "🔑 授予 Firebase Admin 權限..." -ForegroundColor Yellow
gcloud projects add-iam-policy-binding $PROJECT_ID `
  --member="serviceAccount:$SERVICE_ACCOUNT" `
  --role="roles/firebase.admin" `
  --condition=None

# 授予 Datastore User 權限（如果需要）
Write-Host "🔑 授予 Datastore User 權限..." -ForegroundColor Yellow
gcloud projects add-iam-policy-binding $PROJECT_ID `
  --member="serviceAccount:$SERVICE_ACCOUNT" `
  --role="roles/datastore.user" `
  --condition=None

# 驗證權限
Write-Host ""
Write-Host "✅ 驗證已授予的權限..." -ForegroundColor Green
gcloud projects get-iam-policy $PROJECT_ID `
  --flatten="bindings[].members" `
  --filter="bindings.members:serviceAccount:$SERVICE_ACCOUNT" `
  --format="table(bindings.role)"

Write-Host ""
Write-Host "✅ 權限授予完成！" -ForegroundColor Green
Write-Host ""
Write-Host "⚠️  注意：您還需要在 Firebase Console 中更新 Realtime Database 規則：" -ForegroundColor Yellow
Write-Host "   https://console.firebase.google.com/project/shuttle-system-60d6a/database/shuttle-system-60d6a-default-rtdb/rules"
Write-Host ""
Write-Host "   建議規則請參考 GRANT_FIREBASE_PERMISSIONS.md 文件"

