# GCP 設置驗證命令

## 驗證服務帳號

```bash
gcloud iam service-accounts describe \
  shuttle-system@shuttle-system-487204.iam.gserviceaccount.com \
  --project=shuttle-system-487204
```

**預期輸出**:
- 應該顯示服務帳號的詳細資訊
- 包括 email、displayName、name 等

**如果失敗**:
- 確認專案 ID 正確: `shuttle-system-487204`
- 確認服務帳號名稱正確: `shuttle-system`
- 確認您有權限查看服務帳號

---

## 驗證 Artifact Registry

```bash
gcloud artifacts repositories describe shuttle-web \
  --location=asia-east1 \
  --project=shuttle-system-487204
```

**預期輸出**:
- 應該顯示倉庫的詳細資訊
- 包括 name、format、location 等

**如果失敗**:
- 確認倉庫名稱正確: `shuttle-web`
- 確認位置正確: `asia-east1`
- 確認專案 ID 正確: `shuttle-system-487204`

---

## 驗證服務帳號權限

```bash
gcloud projects get-iam-policy shuttle-system-487204 \
  --flatten="bindings[].members" \
  --filter="bindings.members:serviceAccount:shuttle-system@shuttle-system-487204.iam.gserviceaccount.com" \
  --format="table(bindings.role)"
```

**預期輸出**:
應該看到以下角色：
- `roles/run.serviceAgent`
- `roles/datastore.user`
- `roles/firebase.admin`
- `roles/artifactregistry.writer`
- `roles/cloudbuild.builds.builder`
- `roles/storage.admin`

---

## 驗證 API 啟用狀態

```bash
# 檢查 Cloud Run API
gcloud services list --enabled --project=shuttle-system-487204 | grep run

# 檢查 Artifact Registry API
gcloud services list --enabled --project=shuttle-system-487204 | grep artifactregistry

# 檢查 Cloud Build API
gcloud services list --enabled --project=shuttle-system-487204 | grep cloudbuild

# 檢查 Google Sheets API
gcloud services list --enabled --project=shuttle-system-487204 | grep sheets

# 檢查 Firebase API
gcloud services list --enabled --project=shuttle-system-487204 | grep firebase
```

---

## 驗證專案設置

```bash
# 確認專案存在
gcloud projects describe shuttle-system-487204

# 確認當前專案
gcloud config get-value project
```

---

## 驗證 Docker 認證

```bash
# 測試 Docker 認證
gcloud auth configure-docker asia-east1-docker.pkg.dev --quiet

# 測試推送權限（不會實際推送，只是測試認證）
docker pull hello-world
docker tag hello-world asia-east1-docker.pkg.dev/shuttle-system-487204/shuttle-web/test:latest
# 注意：這個命令會失敗，但可以測試認證是否正確
```

---

## 完整驗證腳本

將以下內容保存為 `verify-gcp-setup.sh` 並執行：

```bash
#!/bin/bash

PROJECT_ID="shuttle-system-487204"
SERVICE_ACCOUNT="shuttle-system@${PROJECT_ID}.iam.gserviceaccount.com"
REGION="asia-east1"
REPOSITORY="shuttle-web"

echo "=== 驗證 GCP 設置 ==="
echo ""

echo "1. 驗證專案..."
gcloud projects describe ${PROJECT_ID} || {
  echo "❌ 專案不存在或無權限訪問"
  exit 1
}
echo "✅ 專案存在"
echo ""

echo "2. 驗證服務帳號..."
gcloud iam service-accounts describe ${SERVICE_ACCOUNT} --project=${PROJECT_ID} || {
  echo "❌ 服務帳號不存在"
  exit 1
}
echo "✅ 服務帳號存在"
echo ""

echo "3. 驗證 Artifact Registry..."
gcloud artifacts repositories describe ${REPOSITORY} \
  --location=${REGION} \
  --project=${PROJECT_ID} || {
  echo "❌ Artifact Registry 不存在"
  exit 1
}
echo "✅ Artifact Registry 存在"
echo ""

echo "4. 驗證服務帳號權限..."
ROLES=$(gcloud projects get-iam-policy ${PROJECT_ID} \
  --flatten="bindings[].members" \
  --filter="bindings.members:serviceAccount:${SERVICE_ACCOUNT}" \
  --format="value(bindings.role)" 2>/dev/null)

if [ -z "$ROLES" ]; then
  echo "❌ 服務帳號沒有權限"
  exit 1
fi

echo "✅ 服務帳號權限:"
echo "$ROLES"
echo ""

echo "5. 驗證 API 啟用..."
APIS=(
  "run.googleapis.com"
  "artifactregistry.googleapis.com"
  "cloudbuild.googleapis.com"
  "sheets.googleapis.com"
  "firebase.googleapis.com"
)

for API in "${APIS[@]}"; do
  if gcloud services list --enabled --project=${PROJECT_ID} --filter="name:${API}" --format="value(name)" | grep -q "${API}"; then
    echo "✅ ${API} 已啟用"
  else
    echo "❌ ${API} 未啟用"
  fi
done

echo ""
echo "=== 驗證完成 ==="
```

---

## 常見問題

### 問題 1: "Permission denied" 或 "Access denied"
**解決方案**: 
- 確認您已登入正確的 Google Cloud 帳號
- 確認您有專案的查看權限
- 執行: `gcloud auth login`

### 問題 2: "Project not found"
**解決方案**:
- 確認專案 ID 正確: `shuttle-system-487204`
- 確認專案存在於您的 Google Cloud 帳號中
- 執行: `gcloud projects list` 查看所有專案

### 問題 3: "Service account not found"
**解決方案**:
- 確認服務帳號名稱正確: `shuttle-system`
- 確認專案 ID 正確
- 執行: `gcloud iam service-accounts list --project=shuttle-system-487204`

### 問題 4: "Repository not found"
**解決方案**:
- 確認倉庫名稱正確: `shuttle-web`
- 確認位置正確: `asia-east1`
- 執行: `gcloud artifacts repositories list --location=asia-east1 --project=shuttle-system-487204`

