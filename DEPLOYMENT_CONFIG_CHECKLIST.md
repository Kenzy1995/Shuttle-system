# 🔍 部署配置完整檢查清單

## 📋 部署目標確認

### ✅ 會部署到新的測試專案
- **專案 ID**: `shuttle-system-487204` (測試環境)
- **正式環境**: `forte-booking-system` (不會被影響)
- **部署區域**: `asia-east1`

---

## 1️⃣ GitHub Secrets 檢查清單

請確認以下 Secrets 已在 GitHub 設置：
**位置**: https://github.com/Kenzy1995/Shuttle-system/settings/secrets/actions

### ✅ GCP_CREDENTIALS
- **值**: 新 Google Cloud 帳號的服務帳號 JSON 完整內容
- **來源**: `gcp-credentials.json` 檔案
- **服務帳號**: `shuttle-system@shuttle-system-487204.iam.gserviceaccount.com`
- **檢查**: 確認 JSON 格式正確，包含 `project_id: "shuttle-system-487204"`

### ✅ GCP_PROJECT_ID
- **值**: `shuttle-system-487204`
- **檢查**: 必須完全匹配，不能有空格或換行

### ✅ FIREBASE_RTDB_URL
- **值**: `https://shuttle-system-60d6a-default-rtdb.asia-southeast1.firebasedatabase.app/`
- **檢查**: 結尾必須有斜線 `/`

### ✅ SMTP_USER
- **值**: Gmail 帳號（例如：`fortehotels.shuttle@gmail.com`）

### ✅ SMTP_PASS
- **值**: Gmail 應用程式密碼（不是 Gmail 密碼）

---

## 2️⃣ Google Cloud 專案設置檢查

### ✅ 專案確認
```bash
# 確認專案存在
gcloud projects describe shuttle-system-487204
```

### ✅ API 啟用確認
確認以下 API 已啟用：
- ✅ Cloud Run API
- ✅ Cloud Build API
- ✅ Artifact Registry API
- ✅ Google Sheets API
- ✅ Firebase API

### ✅ Artifact Registry 確認
```bash
# 確認倉庫存在
gcloud artifacts repositories describe shuttle-web \
  --location=asia-east1 \
  --project=shuttle-system-487204
```

**預期結果**:
- 倉庫名稱: `shuttle-web`
- 位置: `asia-east1`
- 完整路徑: `asia-east1-docker.pkg.dev/shuttle-system-487204/shuttle-web/web`

---

## 3️⃣ 服務帳號檢查

### ✅ 服務帳號存在確認
```bash
# 確認服務帳號存在
gcloud iam service-accounts describe \
  shuttle-system@shuttle-system-487204.iam.gserviceaccount.com \
  --project=shuttle-system-487204
```

**預期資訊**:
- 服務帳號名稱: `shuttle-system`
- 完整郵箱: `shuttle-system@shuttle-system-487204.iam.gserviceaccount.com`
- 顯示名稱: `Shuttle System Service Account`

### ✅ 服務帳號權限確認
確認服務帳號具有以下 IAM 角色：
```bash
# 查看服務帳號權限
gcloud projects get-iam-policy shuttle-system-487204 \
  --flatten="bindings[].members" \
  --filter="bindings.members:serviceAccount:shuttle-system@shuttle-system-487204.iam.gserviceaccount.com"
```

**必需權限**:
- ✅ `roles/run.serviceAgent` - Cloud Run 服務代理
- ✅ `roles/datastore.user` - Datastore 使用者（Google Sheets）
- ✅ `roles/firebase.admin` - Firebase 管理員
- ✅ `roles/artifactregistry.writer` - Artifact Registry 寫入
- ✅ `roles/cloudbuild.builds.builder` - Cloud Build 構建
- ✅ `roles/storage.admin` - Storage 管理員

---

## 4️⃣ Google Sheets 權限檢查

### ✅ 服務帳號已添加為編輯者
1. 打開 Google Sheets: https://docs.google.com/spreadsheets/d/1o_kLeuwP5_G08YYLlZKIgcYzlU1NIZD5SQnHoO59YUw/edit
2. 點擊右上角「共用」
3. 確認以下服務帳號在列表中：
   - `shuttle-system@shuttle-system-487204.iam.gserviceaccount.com`
   - 權限: **編輯者**（不是檢視者）

---

## 5️⃣ GitHub Actions 工作流程檢查

### ✅ 工作流程檔案確認
確認以下檔案存在且配置正確：
- ✅ `.github/workflows/deploy-web.yml`
- ✅ `.github/workflows/deploy-booking-api.yml`
- ✅ `.github/workflows/deploy-booking-manager.yml`
- ✅ `.github/workflows/deploy-driver-api2.yml`

### ✅ Docker 構建命令確認
所有工作流程使用以下格式：
```yaml
docker build -t asia-east1-docker.pkg.dev/${{ secrets.GCP_PROJECT_ID }}/shuttle-web/{SERVICE} -f {SERVICE}/Dockerfile {SERVICE}
```

### ✅ 服務帳號配置確認
所有部署命令使用：
```bash
--service-account=shuttle-system@${{ secrets.GCP_PROJECT_ID }}.iam.gserviceaccount.com
```

### ✅ 專案 ID 配置確認
所有 gcloud 命令使用：
```bash
--project=${{ secrets.GCP_PROJECT_ID }}
```

---

## 6️⃣ 部署服務配置

### ✅ Web 服務
- **服務名稱**: `shuttle-web`
- **映像路徑**: `asia-east1-docker.pkg.dev/{PROJECT_ID}/shuttle-web/web`
- **區域**: `asia-east1`
- **端口**: `8080`

### ✅ Booking API 服務
- **服務名稱**: `booking-api`
- **映像路徑**: `asia-east1-docker.pkg.dev/{PROJECT_ID}/shuttle-web/booking-api`
- **區域**: `asia-east1`
- **記憶體**: `2Gi`
- **CPU**: `2`
- **最大實例**: `10`

### ✅ Booking Manager 服務
- **服務名稱**: `booking-manager`
- **映像路徑**: `asia-east1-docker.pkg.dev/{PROJECT_ID}/shuttle-web/booking-manager`
- **區域**: `asia-east1`
- **記憶體**: `2Gi`
- **CPU**: `2`
- **最大實例**: `10`
- **環境變數**: `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASS`, `FIREBASE_RTDB_URL`

### ✅ Driver API 服務
- **服務名稱**: `driver-api2`
- **映像路徑**: `asia-east1-docker.pkg.dev/{PROJECT_ID}/shuttle-web/driver-api2`
- **區域**: `asia-east1`
- **記憶體**: `1Gi`
- **CPU**: `1`
- **最大實例**: `5`
- **環境變數**: `FIREBASE_RTDB_URL`

---

## 7️⃣ API Keys 配置檢查

### ✅ Google Maps API Key
- **位置**: `web/app.js` 第 11 行
- **當前值**: `AIzaSyB1PtwlsIgr026u29gU2L8ZXcozbkHpHco`
- **檢查**: 確認 API Key 在 Google Cloud Console 中已啟用並限制正確

### ✅ Firebase 配置
- **Database URL**: `https://shuttle-system-60d6a-default-rtdb.asia-southeast1.firebasedatabase.app/`
- **API Key**: `AIzaSyDatr-z00tNMnXD7WMoTJ0vygdVCJKNuQA`
- **位置**: `web/app.js` 第 14-15 行

---

## 8️⃣ 部署驗證步驟

### 步驟 1: 檢查 GitHub Actions
1. 前往: https://github.com/Kenzy1995/Shuttle-system/actions
2. 確認最新工作流程執行成功
3. 檢查是否有錯誤訊息

### 步驟 2: 檢查 Cloud Run 服務
```bash
# 列出所有服務
gcloud run services list \
  --region=asia-east1 \
  --project=shuttle-system-487204
```

**預期服務**:
- `shuttle-web`
- `booking-api`
- `booking-manager`
- `driver-api2`

### 步驟 3: 獲取服務 URL
```bash
# 獲取 Web 服務 URL
gcloud run services describe shuttle-web \
  --region=asia-east1 \
  --format='value(status.url)' \
  --project=shuttle-system-487204
```

### 步驟 4: 測試服務
- Web: 訪問服務 URL，確認頁面載入
- Booking API: `{URL}/api/sheet` 應該返回 JSON
- Booking Manager: `{URL}/api/ops` 應該返回 JSON
- Driver API: `{URL}/health` 應該返回 `{"status": "ok"}`

---

## ⚠️ 常見問題排查

### 問題 1: Docker 構建失敗
**錯誤**: `docker buildx build requires 1 argument`
**解決方案**: ✅ 已修復 - 使用 `-f` 參數指定 Dockerfile 路徑

### 問題 2: 認證失敗
**錯誤**: `Permission denied` 或 `Authentication failed`
**檢查**:
1. 確認 `GCP_CREDENTIALS` Secret 格式正確
2. 確認服務帳號有正確權限
3. 確認專案 ID 正確

### 問題 3: Artifact Registry 推送失敗
**錯誤**: `denied: Permission denied`
**檢查**:
1. 確認 `roles/artifactregistry.writer` 權限已授予
2. 確認 Artifact Registry 倉庫存在
3. 確認 Docker 認證配置正確

### 問題 4: Cloud Run 部署失敗
**錯誤**: `Service account not found`
**檢查**:
1. 確認服務帳號存在: `shuttle-system@shuttle-system-487204.iam.gserviceaccount.com`
2. 確認服務帳號名稱正確（不是 `forte-booking-system`）

---

## ✅ 最終確認清單

在部署前，請確認：

- [ ] 所有 5 個 GitHub Secrets 已設置
- [ ] GCP 專案 `shuttle-system-487204` 存在
- [ ] 所有必需的 API 已啟用
- [ ] Artifact Registry 倉庫 `shuttle-web` 存在
- [ ] 服務帳號 `shuttle-system` 存在並有正確權限
- [ ] Google Sheets 已添加服務帳號為編輯者
- [ ] 所有工作流程檔案已更新
- [ ] Docker 構建命令已修復
- [ ] 專案 ID 在所有配置中為 `shuttle-system-487204`
- [ ] 服務帳號在所有配置中為 `shuttle-system@shuttle-system-487204.iam.gserviceaccount.com`

---

## 📞 需要幫助？

如果遇到問題：
1. 檢查 GitHub Actions 日誌: https://github.com/Kenzy1995/Shuttle-system/actions
2. 檢查 GCP Console: https://console.cloud.google.com/
3. 確認所有 Secrets 設置正確
4. 驗證服務帳號權限

