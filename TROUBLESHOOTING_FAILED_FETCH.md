# 🔧 修復 "Failed to fetch" 錯誤

## ❌ 錯誤訊息

前端網站顯示：**"資料更新失敗：Failed to fetch"**

---

## 🔍 診斷步驟

### 步驟 1: 檢查瀏覽器控制台

1. 打開前端網站: https://shuttle-web-509045429779.asia-east1.run.app
2. 按 `F12` 打開開發者工具
3. 切換到 **Console** 標籤
4. 查看完整的錯誤訊息
5. 切換到 **Network** 標籤
6. 重新載入頁面或觸發預約操作
7. 查看失敗的請求：
   - 請求 URL
   - 狀態碼（如 404, 500, CORS 錯誤等）
   - 響應內容

### 步驟 2: 檢查 API 服務狀態

#### 檢查 booking-api
```bash
# 測試健康檢查端點
curl https://booking-api-509045429779.asia-east1.run.app/health

# 測試 API 端點
curl https://booking-api-509045429779.asia-east1.run.app/api/sheet
```

#### 檢查 booking-manager
```bash
# 測試健康檢查端點
curl https://booking-manager-509045429779.asia-east1.run.app/health

# 測試 CORS 調試端點
curl https://booking-manager-509045429779.asia-east1.run.app/cors_debug
```

#### 檢查 driver-api2
```bash
# 測試健康檢查端點
curl https://driver-api2-509045429779.asia-east1.run.app/health
```

### 步驟 3: 檢查 CORS 設置

#### 測試 CORS 響應標頭

使用瀏覽器控制台執行：

```javascript
// 測試 booking-api
fetch('https://booking-api-509045429779.asia-east1.run.app/api/sheet', {
  method: 'GET',
  headers: {
    'Content-Type': 'application/json'
  }
})
.then(response => {
  console.log('Status:', response.status);
  console.log('CORS Headers:', {
    'Access-Control-Allow-Origin': response.headers.get('Access-Control-Allow-Origin'),
    'Access-Control-Allow-Methods': response.headers.get('Access-Control-Allow-Methods'),
    'Access-Control-Allow-Headers': response.headers.get('Access-Control-Allow-Headers')
  });
  return response.json();
})
.then(data => console.log('Data:', data))
.catch(error => console.error('Error:', error));
```

### 步驟 4: 檢查 Cloud Run 服務日誌

```bash
# 查看 booking-api 日誌
gcloud run services logs read booking-api \
  --region=asia-east1 \
  --project=shuttle-system-487204 \
  --limit=50

# 查看 booking-manager 日誌
gcloud run services logs read booking-manager \
  --region=asia-east1 \
  --project=shuttle-system-487204 \
  --limit=50
```

---

## 🔧 常見問題和解決方案

### 問題 1: CORS 錯誤

**錯誤訊息**: `Access to fetch at '...' from origin '...' has been blocked by CORS policy`

**解決方案**:
1. 確認 API 服務的 CORS 設置包含前端 URL
2. 檢查 `booking-api/server.py` 和 `booking-manager/server.py` 中的 CORS 設置
3. 確認允許的來源包含: `https://shuttle-web-509045429779.asia-east1.run.app`

### 問題 2: 404 Not Found

**錯誤訊息**: `Failed to fetch` 或 `404 Not Found`

**解決方案**:
1. 確認 API 端點路徑正確
2. 檢查 API 服務是否正常運行
3. 驗證服務 URL 是否正確

### 問題 3: 500 Internal Server Error

**錯誤訊息**: `Failed to fetch` 或 `500 Internal Server Error`

**解決方案**:
1. 查看 Cloud Run 服務日誌
2. 檢查服務帳號權限
3. 確認 Google Sheets 權限設置
4. 檢查 Firebase 連接

### 問題 4: SSL 證書問題

**錯誤訊息**: `net::ERR_CERT_*` 或 SSL 相關錯誤

**解決方案**:
1. Cloud Run 自動提供 SSL 證書，通常不會有問題
2. 如果遇到問題，檢查服務是否正確部署
3. 確認服務 URL 使用 HTTPS

### 問題 5: 服務未啟動

**錯誤訊息**: `Failed to fetch` 或連接超時

**解決方案**:
1. 檢查 Cloud Run 服務狀態：
   ```bash
   gcloud run services list \
     --region=asia-east1 \
     --project=shuttle-system-487204
   ```
2. 確認服務正在運行
3. 檢查服務配置是否正確

---

## ✅ 驗證清單

在修復問題前，請確認：

- [ ] 所有 API 服務正常運行
- [ ] CORS 設置正確
- [ ] 前端 URL 在 CORS 允許列表中
- [ ] API 端點路徑正確
- [ ] 服務帳號有正確權限
- [ ] Google Sheets 權限設置正確
- [ ] Firebase 連接正常
- [ ] 沒有網路防火牆阻擋

---

## 📝 檢查 API 配置

### booking-api CORS 設置

確認 `booking-api/server.py` 中包含：

```python
CORS(app, 
     origins=[
    "https://shuttle-web-509045429779.asia-east1.run.app",
    "http://localhost:8080",
     ],
     supports_credentials=True,
     allow_headers=["Content-Type", "Authorization"],
     methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"])
```

### booking-manager CORS 設置

確認 `booking-manager/server.py` 中包含：

```python
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://shuttle-web-509045429779.asia-east1.run.app",
        "http://localhost:8080",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
```

---

## 🔗 相關連結

- 前端網站: https://shuttle-web-509045429779.asia-east1.run.app
- Booking API: https://booking-api-509045429779.asia-east1.run.app
- Booking Manager: https://booking-manager-509045429779.asia-east1.run.app
- Driver API: https://driver-api2-509045429779.asia-east1.run.app
- Cloud Run 服務: https://console.cloud.google.com/run?project=shuttle-system-487204

