# ✅ Firebase 設置完成指南

## 🎯 新的 Firebase 配置

**新的 Firebase Realtime Database URL**：
- `https://shuttle-system-487204-default-rtdb.asia-southeast1.firebasedatabase.app/`

**GCP 專案**：`shuttle-system-487204`（測試環境）

---

## ✅ 已完成的更新

### 1. 代碼更新

已更新以下文件：
- ✅ `booking-manager/server.py` - 默認專案 ID 更新為 `shuttle-system-487204`
- ✅ `booking-api/server.py` - 默認專案 ID 更新為 `shuttle-system-487204`
- ✅ `driver-api2/server.py` - 所有默認專案 ID 更新為 `shuttle-system-487204`
- ✅ `web/app.js` - Firebase URL 更新為新的 URL

---

## 📋 需要手動完成的步驟

### 步驟 1: 更新 GitHub Secret

**更新 `FIREBASE_RTDB_URL`**：

1. 前往 GitHub Secrets：
   - https://github.com/Kenzy1995/Shuttle-system/settings/secrets/actions

2. 找到 `FIREBASE_RTDB_URL` 並更新為：
   - **新值**：`https://shuttle-system-487204-default-rtdb.asia-southeast1.firebasedatabase.app/`

### 步驟 2: 設置 Firebase 規則

1. **前往 Firebase Console**：
   - https://console.firebase.google.com/project/shuttle-system-487204/database/shuttle-system-487204-default-rtdb/rules

2. **設置規則**（與舊版本一致）：
   ```json
   {
     "rules": {
       ".read": false,
       ".write": false,

       "sheet_locks": {
         ".read": false,
         ".write": false
       },

       "booking_seq": {
         ".read": false,
         ".write": false
       },

       "realtime_locations": {
         ".read": "auth != null",
         ".write": "auth != null"
       }
     }
   }
   ```

3. **發布規則**

### 步驟 3: 確認 Firebase 路徑（可選）

後端會自動初始化必要的路徑，但您可以手動檢查：

1. **前往 Firebase Console**：
   - https://console.firebase.google.com/project/shuttle-system-487204/database/shuttle-system-487204-default-rtdb/data

2. **確認路徑存在**（後端啟動後會自動創建）：
   - `/sheet_locks`（空對象 `{}`）
   - `/booking_seq`（空對象 `{}`）

---

## 🚀 部署流程

### 1. 更新 GitHub Secret

完成步驟 1 後，GitHub Actions 會自動使用新的 Firebase URL。

### 2. 觸發部署

代碼已提交，GitHub Actions 會自動部署。或者您可以：
- 手動觸發部署：在 GitHub Actions 中點擊「Run workflow」
- 或者等待下一次代碼推送

### 3. 驗證部署

部署後，檢查 Cloud Run 日誌應該看到：
- ✅ `Firebase: Using FIREBASE_RTDB_URL from env: https://shuttle-system-487204-default-rtdb.asia-southeast1.firebasedatabase.app/`
- ✅ `Firebase: Initialization successful`
- ✅ `Firebase: Initialized path /sheet_locks`
- ✅ `Firebase: Initialized path /booking_seq`

---

## 🔍 測試步驟

### 1. 檢查服務狀態

確認所有服務正常運行：
- ✅ `booking-api`
- ✅ `booking-manager`
- ✅ `driver-api2`
- ✅ `shuttle-web`

### 2. 測試預約功能

1. 打開前端網站
2. 嘗試進行一次預約
3. 確認：
   - ✅ 不再出現 `UnauthenticatedError`
   - ✅ 鎖定正常獲取
   - ✅ 預約成功

### 3. 檢查 Firebase 數據

前往 Firebase Console 確認：
- ✅ `/sheet_locks` 路徑存在
- ✅ `/booking_seq` 路徑存在
- ✅ 預約數據正常寫入

---

## 🔗 相關連結

- Firebase Console：https://console.firebase.google.com/project/shuttle-system-487204
- Firebase Realtime Database：https://console.firebase.google.com/project/shuttle-system-487204/database/shuttle-system-487204-default-rtdb/data
- Firebase 規則：https://console.firebase.google.com/project/shuttle-system-487204/database/shuttle-system-487204-default-rtdb/rules
- GitHub Secrets：https://github.com/Kenzy1995/Shuttle-system/settings/secrets/actions
- Cloud Run 服務：https://console.cloud.google.com/run?project=shuttle-system-487204

---

## ⚠️ 重要提示

1. **服務帳號權限**：因為 Firebase 專案和 GCP 專案是同一個（`shuttle-system-487204`），服務帳號 `shuttle-system@shuttle-system-487204.iam.gserviceaccount.com` 應該自動有權限訪問 Firebase。

2. **自動初始化**：後端會在啟動時自動創建 `/sheet_locks` 和 `/booking_seq` 路徑，無需手動創建。

3. **規則設置**：確保 Firebase 規則設置為與舊版本一致（`false`），因為 Firebase Admin SDK 會繞過規則。

---

## 🎯 完成檢查清單

- [ ] 更新 GitHub Secret `FIREBASE_RTDB_URL`
- [ ] 設置 Firebase 規則
- [ ] 等待自動部署完成
- [ ] 檢查日誌確認 Firebase 初始化成功
- [ ] 測試預約功能
- [ ] 確認 Firebase 數據正常寫入

---

## 🎉 完成後

完成所有步驟後，測試環境應該可以正常運作，所有服務都使用同一個 GCP 專案 `shuttle-system-487204`，包括 Firebase。

