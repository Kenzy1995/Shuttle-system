# 🔄 後端服務合併計劃

## 📊 現有服務分析

### 1. **booking-api** (Flask)
- **端點**：
  - `GET /api/sheet` - 讀取 Google Sheets 班次資料
  - `GET /api/health` - 健康檢查
  - `GET /api/realtime/location` - 即時位置資料
- **依賴**：Flask, gunicorn, google-api-python-client, firebase-admin
- **功能**：讀取班次資料、提供即時位置 API

### 2. **booking-manager** (FastAPI)
- **端點**：
  - `POST /api/ops` - 預約操作（book, modify, cancel, query）
  - `GET /api/qr/{code}` - QR Code 生成
  - `GET /health` - 健康檢查
  - `GET /api/debug` - 除錯端點
- **依賴**：FastAPI, uvicorn, gunicorn, gspread, qrcode, Pillow
- **功能**：預約管理、QR Code 生成、郵件發送

### 3. **driver-api2** (FastAPI)
- **端點**：
  - `POST /api/driver/location` - 更新司機位置
  - `GET /api/driver/location` - 獲取司機位置
  - `GET /api/driver/data` - 司機資料
  - `GET /api/driver/trips` - 行程資料
  - `GET /api/driver/passenger_list` - 乘客名單
  - `POST /api/driver/checkin` - 登入
  - `POST /api/driver/no_show` - 未到
  - `POST /api/driver/manual_boarding` - 手動登車
  - `POST /api/driver/trip_status` - 行程狀態
  - `POST /api/driver/qrcode_info` - QR Code 資訊
  - `POST /api/driver/google/trip_start` - Google 行程開始
  - `POST /api/driver/google/trip_complete` - Google 行程完成
  - `GET /api/driver/route` - 路線
  - `GET /api/driver/system_status` - 系統狀態
  - `POST /api/driver/system_status` - 更新系統狀態
  - `POST /api/driver/update_station` - 更新站點
  - `GET /health` - 健康檢查
- **依賴**：FastAPI, uvicorn, gunicorn, gspread, firebase-admin
- **功能**：司機端管理、GPS 追蹤、行程管理

---

## 🎯 合併目標

將三個後端服務合併為**單一統一後端服務** (`shuttle-api`)，使用 FastAPI 框架。

### 優點：
1. **簡化部署**：只需部署一個服務
2. **統一管理**：所有 API 端點集中管理
3. **減少資源**：降低 Cloud Run 實例數量
4. **統一配置**：共享配置和依賴
5. **易於維護**：單一代碼庫

---

## 📋 合併計劃（分階段執行）

### 階段 1: 準備工作 ✅
- [x] 分析現有服務結構
- [x] 識別所有 API 端點
- [x] 分析依賴關係
- [ ] 創建合併計劃文檔

### 階段 2: 創建統一後端結構
- [ ] 創建 `shuttle-api` 目錄
- [ ] 合併所有依賴到 `requirements.txt`
- [ ] 創建統一的 `server.py`
- [ ] 設置統一的 CORS 配置
- [ ] 設置統一的 Firebase 初始化
- [ ] 設置統一的 Google Sheets 初始化

### 階段 3: 遷移 booking-api 功能
- [ ] 遷移 `/api/sheet` 端點
- [ ] 遷移 `/api/realtime/location` 端點
- [ ] 遷移快取機制
- [ ] 測試功能

### 階段 4: 遷移 booking-manager 功能
- [ ] 遷移 `/api/ops` 端點
- [ ] 遷移 `/api/qr/{code}` 端點
- [ ] 遷移 QR Code 生成邏輯
- [ ] 遷移郵件發送邏輯
- [ ] 遷移 Firebase 鎖機制
- [ ] 測試功能

### 階段 5: 遷移 driver-api2 功能
- [ ] 遷移所有 `/api/driver/*` 端點
- [ ] 遷移 GPS 追蹤邏輯
- [ ] 遷移行程管理邏輯
- [ ] 遷移站點管理邏輯
- [ ] 測試功能

### 階段 6: 統一配置和優化
- [ ] 統一環境變數
- [ ] 統一錯誤處理
- [ ] 統一日誌記錄
- [ ] 優化性能
- [ ] 添加 API 文檔

### 階段 7: 更新前端配置
- [ ] 更新 `web/app.js` 中的 API URL
- [ ] 更新所有 API 調用
- [ ] 測試前端功能

### 階段 8: 更新部署配置
- [ ] 創建新的 Dockerfile
- [ ] 更新 GitHub Actions workflow
- [ ] 更新 Cloud Run 配置
- [ ] 測試部署

### 階段 9: 測試和驗證
- [ ] 端到端測試
- [ ] 性能測試
- [ ] 壓力測試
- [ ] 驗證所有功能

### 階段 10: 切換和清理
- [ ] 部署新服務
- [ ] 更新 DNS/URL
- [ ] 監控運行狀態
- [ ] 刪除舊服務（可選）
- [ ] 更新文檔

---

## 🏗️ 新服務結構

```
shuttle-api/
├── server.py              # 主應用文件（合併所有功能）
├── requirements.txt       # 統一依賴
├── Dockerfile            # Docker 配置
├── modules/               # 模組化組織（可選）
│   ├── booking.py        # 預約相關功能
│   ├── driver.py         # 司機相關功能
│   ├── sheets.py         # Google Sheets 工具
│   ├── firebase.py       # Firebase 工具
│   └── utils.py          # 通用工具
└── .env.example          # 環境變數範例
```

---

## 🔌 API 端點規劃

### 統一後端 API 結構：

```
GET  /health                          # 健康檢查
GET  /api/sheet                       # 讀取班次資料（原 booking-api）
GET  /api/realtime/location           # 即時位置（原 booking-api）
POST /api/ops                         # 預約操作（原 booking-manager）
GET  /api/qr/{code}                   # QR Code（原 booking-manager）
POST /api/driver/location             # 司機位置（原 driver-api2）
GET  /api/driver/location             # 獲取司機位置（原 driver-api2）
GET  /api/driver/data                 # 司機資料（原 driver-api2）
GET  /api/driver/trips                # 行程資料（原 driver-api2）
GET  /api/driver/passenger_list        # 乘客名單（原 driver-api2）
POST /api/driver/checkin               # 登入（原 driver-api2）
POST /api/driver/no_show              # 未到（原 driver-api2）
POST /api/driver/manual_boarding      # 手動登車（原 driver-api2）
POST /api/driver/trip_status          # 行程狀態（原 driver-api2）
POST /api/driver/qrcode_info          # QR Code 資訊（原 driver-api2）
POST /api/driver/google/trip_start    # Google 行程開始（原 driver-api2）
POST /api/driver/google/trip_complete # Google 行程完成（原 driver-api2）
GET  /api/driver/route                # 路線（原 driver-api2）
GET  /api/driver/system_status        # 系統狀態（原 driver-api2）
POST /api/driver/system_status        # 更新系統狀態（原 driver-api2）
POST /api/driver/update_station       # 更新站點（原 driver-api2）
```

---

## 📦 依賴合併

### 統一 requirements.txt：

```txt
# Web Framework
fastapi>=0.110
uvicorn>=0.23
gunicorn>=21.2

# Google APIs
gspread>=5.7
google-auth>=2.23
google-auth-httplib2>=0.2.0
google-api-python-client>=2.124.0

# Firebase
firebase-admin>=6.4

# Data Validation
pydantic>=2.6
pydantic-core>=2.16

# QR Code
qrcode[pil]>=7.4
Pillow>=10.0

# Utilities
python-multipart>=0.0.9
```

---

## ⚙️ 環境變數

### 統一環境變數配置：

```bash
# Google Cloud
GOOGLE_CLOUD_PROJECT=shuttle-system-487204
GCP_PROJECT_ID=shuttle-system-487204

# Firebase
FIREBASE_RTDB_URL=https://shuttle-system-487204-default-rtdb.asia-southeast1.firebasedatabase.app/

# Google Sheets
SPREADSHEET_ID=1o_kLeuwP5_G08YYLlZKIgcYzlU1NIZD5SQnHoO59YUw

# SMTP (for email)
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=your-email@gmail.com
SMTP_PASSWORD=your-password

# Port
PORT=8080
```

---

## 🚀 部署配置

### 新的 GitHub Actions Workflow：

- **單一部署流程**：`deploy-shuttle-api.yml`
- **單一 Cloud Run 服務**：`shuttle-api`
- **單一 Artifact Registry**：`shuttle-api`

---

## ⚠️ 注意事項

1. **向後兼容**：確保所有現有 API 端點保持不變
2. **測試充分**：每個階段都要充分測試
3. **逐步遷移**：可以並行運行新舊服務，逐步切換
4. **監控**：密切監控新服務的運行狀態
5. **回滾計劃**：準備回滾方案以防問題

---

## 📅 預估時間

- **階段 1-2**：準備和結構創建（1-2 天）
- **階段 3-5**：功能遷移（3-5 天）
- **階段 6-7**：配置和前端更新（1-2 天）
- **階段 8-9**：部署和測試（2-3 天）
- **階段 10**：切換和清理（1 天）

**總計**：約 8-13 天

---

## 🎯 下一步

1. 確認合併計劃
2. 開始階段 2：創建統一後端結構
3. 逐步遷移功能
4. 測試和驗證
5. 部署和切換

