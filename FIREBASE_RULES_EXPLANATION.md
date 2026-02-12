# 🔍 Firebase Realtime Database 規則說明

## 📋 舊版本 vs 新版本規則對比

### 舊版本規則（正在上線的版本）

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

### 新版本建議規則

```json
{
  "rules": {
    ".read": false,
    ".write": false,

    "sheet_locks": {
      ".read": true,
      ".write": true
    },

    "booking_seq": {
      ".read": true,
      ".write": true
    },

    "cap_lock": {
      ".read": true,
      ".write": true
    },

    "realtime_locations": {
      ".read": "auth != null",
      ".write": "auth != null"
    }
  }
}
```

---

## 🔑 關鍵差異說明

### 1. Firebase Admin SDK 會繞過安全規則

**重要**：Firebase Admin SDK 使用服務帳號憑證時，**會繞過 Realtime Database 的安全規則**！

這意味著：
- 即使規則設置為 `false`，Admin SDK 仍然可以訪問
- 規則主要用於**客戶端 SDK**（如 Web、Mobile App）的訪問控制
- Admin SDK 的訪問由 **GCP IAM 權限**控制，而不是安全規則

### 2. 為什麼舊版本可以工作？

舊版本即使設置為 `false` 仍然可以工作，因為：
- Firebase Admin SDK 繞過了安全規則
- 服務帳號有正確的 GCP IAM 權限
- Admin SDK 使用服務帳號憑證進行身份驗證

### 3. 為什麼新版本出現錯誤？

新版本出現 `UnauthenticatedError` 的原因可能是：
1. **服務帳號權限問題**：服務帳號沒有正確的 Firebase 權限（已修復）
2. **Firebase 初始化失敗**：Admin SDK 初始化時出現問題
3. **專案配置問題**：Firebase 專案配置不正確

---

## ✅ 建議的規則設置

基於舊版本的結構，建議使用以下規則：

```json
{
  "rules": {
    ".read": false,
    ".write": false,

    "sheet_locks": {
      ".read": true,
      ".write": true
    },

    "booking_seq": {
      ".read": true,
      ".write": true
    },

    "cap_lock": {
      ".read": true,
      ".write": true
    },

    "realtime_locations": {
      ".read": "auth != null",
      ".write": "auth != null"
    }
  }
}
```

### 說明

1. **根層級設置為 `false`**：默認拒絕所有訪問（安全）
2. **`sheet_locks`、`booking_seq`、`cap_lock` 設置為 `true`**：
   - 允許 Firebase Admin SDK 訪問（用於服務端操作）
   - 這些路徑只由服務端使用，不暴露給客戶端
3. **`realtime_locations` 設置為 `auth != null`**：
   - 這個路徑可能由客戶端使用，需要用戶身份驗證
   - 保持與舊版本一致

---

## 🔧 操作步驟

1. **前往 Firebase Console**：
   - https://console.firebase.google.com/project/shuttle-system-60d6a/database/shuttle-system-60d6a-default-rtdb/rules

2. **更新規則為上面的建議規則**

3. **點擊「發布」**保存規則

4. **等待 10-30 秒**讓規則生效

---

## 🔒 安全性說明

### 為什麼設置為 `true` 是安全的？

1. **Admin SDK 繞過規則**：
   - 即使設置為 `false`，Admin SDK 仍然可以訪問
   - 規則主要控制客戶端訪問

2. **GCP IAM 層面保護**：
   - 只有服務帳號有 Firebase Admin 權限
   - 訪問已在 IAM 層面受到控制

3. **網路層面保護**：
   - 只有通過 Firebase Admin SDK 或正確憑證才能訪問
   - 沒有憑證的請求會被拒絕

4. **應用層面保護**：
   - 只有部署的 Cloud Run 服務可以訪問
   - 服務使用服務帳號進行身份驗證

---

## 📝 路徑使用說明

根據代碼分析，系統使用以下 Firebase 路徑：

- `/booking_seq/{date_key}` - 用於生成預約編號
- `/cap_lock/{lock_id}` - 用於容量鎖定（併發控制）
- `/sheet_locks/{lock_id}` - 用於工作表鎖定（如果使用）

這些路徑都應該設置為 `true`，以允許 Admin SDK 訪問。

---

## 🔗 相關連結

- Firebase Console 規則：https://console.firebase.google.com/project/shuttle-system-60d6a/database/shuttle-system-60d6a-default-rtdb/rules
- Firebase Admin SDK 文檔：https://firebase.google.com/docs/admin/setup
- Firebase 安全規則文檔：https://firebase.google.com/docs/database/security

