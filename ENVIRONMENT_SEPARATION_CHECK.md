# 🔍 環境分離檢查報告

## ✅ 已確認正確的配置

### 1. 前端 API URLs (web/app.js)
- ✅ `API_URL`: `https://booking-api-509045429779.asia-east1.run.app/api/sheet`
- ✅ `OPS_URL`: `https://booking-manager-509045429779.asia-east1.run.app/api/ops`
- ✅ `QR_ORIGIN`: `https://booking-manager-509045429779.asia-east1.run.app`
- ✅ `driver-api2`: `https://driver-api2-509045429779.asia-east1.run.app`

### 2. CORS 設置

#### booking-api (server.py)
- ✅ 允許來源: `https://shuttle-web-509045429779.asia-east1.run.app`
- ✅ 允許來源: `http://localhost:8080`

#### booking-manager (server.py)
- ✅ 允許來源: `https://shuttle-web-509045429779.asia-east1.run.app`
- ✅ 允許來源: `http://localhost:8080`

#### driver-api2 (server.py)
- ⚠️ 需要檢查 CORS 設置

### 3. GitHub Actions 工作流程
- ✅ 所有工作流程使用 `${{ secrets.GCP_PROJECT_ID }}`
- ✅ 所有工作流程使用 `shuttle-system@${{ secrets.GCP_PROJECT_ID }}.iam.gserviceaccount.com`
- ✅ 所有工作流程使用 `asia-east1-docker.pkg.dev/${{ secrets.GCP_PROJECT_ID }}/shuttle-web/...`

---

## ❌ 發現的舊配置（需要修復）

### 1. web/cloudbuild.yaml
- ❌ 使用 `gcr.io/$PROJECT_ID/hotel-web`（舊的 Container Registry）
- ❌ 服務名稱: `hotel-web`（應該是 `shuttle-web`）
- ⚠️ 此檔案可能不會被使用（因為使用 GitHub Actions）

### 2. web/cloudbuild-rebuild.yaml
- ❌ 使用 `hotel-web` 服務名稱
- ❌ 使用 `forte-booking-system@forte-booking-system.iam.gserviceaccount.com` 服務帳號
- ⚠️ 此檔案可能不會被使用（因為使用 GitHub Actions）

### 3. README.md
- ❌ 包含舊的 URL: `https://hotel-web-995728097341.asia-east1.run.app`

---

## 🔧 需要修復的問題

### 問題 1: "Failed to fetch" 錯誤

**可能原因**:
1. CORS 設置不正確
2. API 服務未正確啟動
3. 網路連接問題
4. SSL 證書問題

**檢查步驟**:
1. 檢查瀏覽器控制台的完整錯誤訊息
2. 檢查 Network 標籤中的請求詳情
3. 確認 API 服務是否正常運行
4. 檢查 CORS 響應標頭

### 問題 2: 環境分離

**需要確保**:
- ✅ 所有服務使用新的專案 ID: `shuttle-system-487204`
- ✅ 所有服務使用新的服務帳號: `shuttle-system@shuttle-system-487204.iam.gserviceaccount.com`
- ✅ 所有服務使用新的 Artifact Registry: `shuttle-web`
- ✅ 所有服務使用新的服務名稱: `shuttle-web`, `booking-api`, `booking-manager`, `driver-api2`

---

## 📋 修復清單

- [ ] 更新或刪除 `web/cloudbuild.yaml`
- [ ] 更新或刪除 `web/cloudbuild-rebuild.yaml`
- [ ] 更新 `README.md` 中的舊 URL
- [ ] 檢查 driver-api2 的 CORS 設置
- [ ] 驗證所有 API 服務的 CORS 響應標頭
- [ ] 檢查錯誤日誌以診斷 "Failed to fetch" 問題

