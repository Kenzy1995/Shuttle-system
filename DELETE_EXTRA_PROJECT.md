# 🗑️ 刪除多餘的 GCP 專案

## 📋 當前情況

您有兩個 GCP 專案：
1. **`shuttle-system-487204`** - 測試環境專案（應該保留）
2. **`shuttle-system-60d6a`** - 多餘的專案（應該刪除）

---

## ✅ 確認要保留的專案

**保留**：`shuttle-system-487204`（測試環境專案）

**刪除**：`shuttle-system-60d6a`（多餘的專案）

---

## 🔧 刪除專案前的準備

### 1. 確認專案中沒有重要資源

在刪除 `shuttle-system-60d6a` 之前，請確認：
- [ ] 沒有重要的 Cloud Run 服務
- [ ] 沒有重要的 Artifact Registry 映像
- [ ] 沒有重要的 Firebase 數據（如果有的話）
- [ ] 沒有其他重要資源

### 2. 如果 `shuttle-system-60d6a` 包含 Firebase 專案

如果 `shuttle-system-60d6a` 包含 Firebase 專案，您需要：
1. **在 `shuttle-system-487204` 中創建新的 Firebase 專案**
2. **更新配置**（見下方）

---

## 🗑️ 刪除專案步驟

### 方法 1: 通過 GCP Console 刪除

1. **前往 GCP Console**：
   - https://console.cloud.google.com/home/dashboard

2. **選擇要刪除的專案**：
   - 點擊專案選擇器
   - 選擇 `shuttle-system-60d6a`

3. **刪除專案**：
   - 前往：https://console.cloud.google.com/iam-admin/settings?project=shuttle-system-60d6a
   - 點擊「刪除專案」或「Delete project」
   - 輸入專案 ID 確認刪除

### 方法 2: 通過 gcloud 命令刪除

```bash
# 設置要刪除的專案
gcloud config set project shuttle-system-60d6a

# 刪除專案（需要確認）
gcloud projects delete shuttle-system-60d6a
```

**注意**：刪除專案是不可逆的操作，請確認後再執行。

---

## 🔧 如果需要在測試環境中創建新的 Firebase 專案

如果 `shuttle-system-60d6a` 包含 Firebase 專案，刪除後需要在 `shuttle-system-487204` 中創建新的 Firebase 專案：

### 步驟 1: 在 Firebase Console 中創建新專案

1. **前往 Firebase Console**：
   - https://console.firebase.google.com/

2. **創建新專案**：
   - 點擊「新增專案」或「Add project」
   - 選擇現有的 GCP 專案：`shuttle-system-487204`
   - 創建 Firebase Realtime Database

3. **獲取新的 Firebase URL**：
   - 格式：`https://shuttle-system-487204-default-rtdb.{region}.firebasedatabase.app/`

### 步驟 2: 更新配置

#### 更新 GitHub Secrets

1. **更新 `FIREBASE_RTDB_URL`**：
   - 前往：https://github.com/Kenzy1995/Shuttle-system/settings/secrets/actions
   - 更新 `FIREBASE_RTDB_URL` 為新的 Firebase URL

#### 更新前端配置

更新 `web/app.js` 中的 Firebase URL：

```javascript
const LIVE_LOCATION_CONFIG = {
  key: "AIzaSyB1PtwlsIgr026u29gU2L8ZXcozbkHpHco",
  api: "https://driver-api2-509045429779.asia-east1.run.app",
  trip: "",
  fbdb: "https://shuttle-system-487204-default-rtdb.{region}.firebasedatabase.app/",
  fbkey: "新的 Firebase API Key"
};
```

---

## 📋 刪除專案後的檢查清單

- [ ] 確認 `shuttle-system-60d6a` 已刪除
- [ ] 確認 `shuttle-system-487204` 是唯一專案
- [ ] 如果刪除了 Firebase 專案，在 `shuttle-system-487204` 中創建新的 Firebase 專案
- [ ] 更新 GitHub Secrets 中的 `FIREBASE_RTDB_URL`
- [ ] 更新前端配置中的 Firebase URL
- [ ] 重新部署服務
- [ ] 測試預約功能

---

## ⚠️ 重要提示

1. **刪除專案是不可逆的**：一旦刪除，所有資源都會被永久刪除
2. **確認沒有重要數據**：刪除前請確認專案中沒有重要資源
3. **備份重要數據**：如果有重要數據，請先備份

---

## 🔗 相關連結

- GCP Console：https://console.cloud.google.com/home/dashboard
- Firebase Console：https://console.firebase.google.com/
- GitHub Secrets：https://github.com/Kenzy1995/Shuttle-system/settings/secrets/actions

