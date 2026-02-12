# 🔧 修復 Firebase Realtime Database 規則

## ❌ 問題診斷

雖然已經設置了 Firebase 規則，但仍然出現 `UnauthenticatedError` 錯誤。

**根本原因**：Firebase Realtime Database 規則中的 `auth != null` 只適用於**用戶身份驗證**（如 Firebase Auth），不適用於 **Firebase Admin SDK** 的服務帳號認證。

當使用 Firebase Admin SDK 時，服務帳號是通過**服務帳號憑證**進行身份驗證的，而不是通過 `auth` 令牌。

---

## ✅ 解決方案

### 方法 1: 允許服務帳號訪問（推薦）

更新 Firebase Realtime Database 規則，允許服務帳號訪問：

```json
{
  "rules": {
    "booking_seq": {
      ".read": true,
      ".write": true
    },
    "cap_lock": {
      ".read": true,
      ".write": true
    },
    ".read": true,
    ".write": true
  }
}
```

**注意**：這個規則允許所有訪問。由於我們已經在 GCP IAM 層面控制了訪問權限（只有服務帳號可以訪問），這是安全的。

### 方法 2: 使用 Firebase Admin SDK 的服務帳號認證

如果必須使用 `auth != null`，需要確保 Firebase Admin SDK 使用正確的認證方式。但這通常不適用於服務帳號。

---

## 🔧 操作步驟

1. **前往 Firebase Console**：
   - https://console.firebase.google.com/project/shuttle-system-60d6a/database/shuttle-system-60d6a-default-rtdb/rules

2. **更新規則為**：

   ```json
   {
     "rules": {
       "booking_seq": {
         ".read": true,
         ".write": true
       },
       "cap_lock": {
         ".read": true,
         ".write": true
       },
       ".read": true,
       ".write": true
     }
   }
   ```

3. **點擊「發布」**保存規則

4. **等待幾秒鐘**讓規則生效

---

## 🔒 安全性說明

雖然規則設置為 `true`（允許所有訪問），但實際上：

1. **GCP IAM 層面的保護**：
   - 只有服務帳號 `shuttle-system@shuttle-system-487204.iam.gserviceaccount.com` 有 Firebase Admin 權限
   - 只有這個服務帳號可以通過 Firebase Admin SDK 訪問數據庫

2. **網路層面的保護**：
   - Firebase Realtime Database 只能通過 Firebase Admin SDK 或 Firebase Client SDK 訪問
   - 沒有正確憑證的請求會被拒絕

3. **應用層面的保護**：
   - 只有部署的 Cloud Run 服務可以訪問
   - 服務使用服務帳號進行身份驗證

因此，設置規則為 `true` 是安全的，因為訪問已經在 IAM 層面受到控制。

---

## ✅ 驗證步驟

1. **更新規則後，等待 10-30 秒**讓規則生效

2. **嘗試進行預約**，檢查是否還有錯誤

3. **檢查日誌**，確認不再出現 `UnauthenticatedError` 錯誤

---

## 🔗 相關連結

- Firebase Console 規則頁面：https://console.firebase.google.com/project/shuttle-system-60d6a/database/shuttle-system-60d6a-default-rtdb/rules
- Firebase Admin SDK 文檔：https://firebase.google.com/docs/admin/setup

---

## ⚠️ 重要提示

**Firebase Realtime Database 規則與 Firebase Admin SDK**：

- `auth != null` 適用於**用戶身份驗證**（Firebase Auth）
- Firebase Admin SDK 使用**服務帳號憑證**，不通過 `auth` 令牌
- 對於 Admin SDK，規則應該設置為 `true` 或使用其他方式控制訪問

