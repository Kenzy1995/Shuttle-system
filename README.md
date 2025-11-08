# Hotel-shuttle-system
# 飯店接駁車預約系統

## 服務架構

- **booking-api**: 讀取班次資料 API
- **booking-manager**: 預約管理 API

## 部署方式

### 1. GitHub Secrets 設定
在 GitHub 倉庫設定中新增以下 secrets:
- `GCP_PROJECT_ID`: Google Cloud 專案 ID
- `GCP_CREDENTIALS`: Google Cloud 服務帳號憑證 JSON

### 2. Cloud Run 環境變數
為每個服務設定環境變數:
- `GOOGLE_CREDENTIALS_JSON`: Google Sheets API 憑證 JSON

### 3. 自動部署
推送到 main 分支時會自動部署對應的服務。

## API 端點

### booking-api
- `GET /api/sheet` - 讀取班次資料
- `GET /health` - 健康檢查

### booking-manager
- `POST /api/book` - 提交預約
- `POST /api/query-orders` - 查詢訂單
- `POST /api/update-booking` - 修改預約
- `POST /api/cancel-booking` - 取消預約
- `GET /health` - 健康檢查
