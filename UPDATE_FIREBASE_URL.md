# ✅ 更新 Firebase URL 配置

## 🎯 新的 Firebase 配置

**新的 Firebase Realtime Database URL**：
- `https://shuttle-system-487204-default-rtdb.asia-southeast1.firebasedatabase.app/`

---

## ✅ 已更新的配置

### 1. 代碼更新

已更新以下文件中的 Firebase URL 和默認專案 ID：

- ✅ `booking-manager/server.py` - 默認專案 ID 更新為 `shuttle-system-487204`
- ✅ `booking-api/server.py` - 默認專案 ID 更新為 `shuttle-system-487204`
- ✅ `driver-api2/server.py` - 所有默認專案 ID 更新為 `shuttle-system-487204`
- ✅ `web/app.js` - Firebase URL 更新為新的 URL

### 2. 需要手動更新的配置

#### GitHub Secrets

請更新 GitHub Secret `FIREBASE_RTDB_URL`：

1. **前往 GitHub Secrets**：
   - https://github.com/Kenzy1995/Shuttle-system/settings/secrets/actions

2. **更新 `FIREBASE_RTDB_URL`**：
   - 舊值：`https://shuttle-system-60d6a-default-rtdb.asia-southeast1.firebasedatabase.app/`
   - **新值**：`https://shuttle-system-487204-default-rtdb.asia-southeast1.firebasedatabase.app/`

#### Firebase 規則設置

請在 Firebase Console 中設置規則：

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

#### Firebase 初始化路徑

後端會自動初始化必要的路徑（`/sheet_locks` 和 `/booking_seq`），但您也可以手動檢查：

1. **前往 Firebase Console**：
   - https://console.firebase.google.com/project/shuttle-system-487204/database/shuttle-system-487204-default-rtdb/data

2. **確認路徑存在**：
   - `/sheet_locks`（空對象 `{}`）
   - `/booking_seq`（空對象 `{}`）

---

## 📋 部署步驟

### 1. 更新 GitHub Secrets

更新 `FIREBASE_RTDB_URL` 為新的 URL。

### 2. 提交代碼更改

代碼已更新，提交並推送：

```bash
git add .
git commit -m "Update Firebase URL to new test environment"
git push origin main
```

### 3. 等待自動部署

GitHub Actions 會自動部署所有服務。

### 4. 驗證部署

部署後，檢查：
- ✅ 服務正常啟動
- ✅ Firebase 初始化成功
- ✅ 路徑自動創建
- ✅ 預約功能正常

---

## 🔍 驗證步驟

### 1. 檢查日誌

部署後，檢查 Cloud Run 日誌應該看到：
- ✅ `Firebase: Using FIREBASE_RTDB_URL from env: https://shuttle-system-487204-default-rtdb.asia-southeast1.firebasedatabase.app/`
- ✅ `Firebase: Initialization successful`
- ✅ `Firebase: Initialized path /sheet_locks`
- ✅ `Firebase: Initialized path /booking_seq`

### 2. 測試預約功能

嘗試進行一次預約，確認：
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

---

## ⚠️ 重要提示

1. **確保 GitHub Secret 已更新**：`FIREBASE_RTDB_URL` 必須更新為新的 URL
2. **確保 Firebase 規則已設置**：規則應該與舊版本一致
3. **確保服務帳號有權限**：服務帳號 `shuttle-system@shuttle-system-487204.iam.gserviceaccount.com` 應該自動有權限（因為在同一個專案中）

---

## 🎯 下一步

1. 更新 GitHub Secret `FIREBASE_RTDB_URL`
2. 提交代碼更改（已準備好）
3. 等待自動部署
4. 測試預約功能

