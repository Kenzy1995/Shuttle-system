# 🔧 修復 Firebase 跨專案訪問問題

## ❌ 問題診斷

從日誌中看到關鍵錯誤：
```
Firebase: Failed to ensure paths: UnauthenticatedError: Unauthorized request.
```

**根本原因**：
- **測試環境 GCP 專案**：`shuttle-system-487204`
- **Firebase 專案**：`shuttle-system-60d6a`（舊的正式環境）
- **服務帳號**：`shuttle-system@shuttle-system-487204.iam.gserviceaccount.com`

**問題**：服務帳號屬於新 GCP 專案，但沒有權限訪問舊的 Firebase 專案。

---

## 🔍 正式環境 vs 測試環境差異

### 正式環境
- GCP 專案和 Firebase 專案可能是同一個，或者服務帳號有權限訪問 Firebase

### 測試環境
- GCP 專案：`shuttle-system-487204`（新）
- Firebase 專案：`shuttle-system-60d6a`（舊）
- **服務帳號沒有權限訪問 Firebase 專案**

---

## ✅ 解決方案

### 方案 1: 在 Firebase 專案中授予服務帳號權限（推薦）

1. **前往 Firebase Console**：
   - https://console.firebase.google.com/project/shuttle-system-60d6a/settings/iam

2. **添加服務帳號**：
   - 點擊「添加成員」
   - 輸入：`shuttle-system@shuttle-system-487204.iam.gserviceaccount.com`
   - 選擇角色：**Firebase Admin** 或 **Firebase Realtime Database Admin**
   - 點擊「添加」

3. **確認權限**：
   - 服務帳號應該出現在成員列表中

### 方案 2: 創建新的 Firebase 專案給測試環境（如果需要完全隔離）

如果希望測試環境完全獨立，可以：
1. 創建新的 Firebase 專案
2. 更新 `FIREBASE_RTDB_URL` 環境變數
3. 更新前端配置

但這需要更多配置，**方案 1 更簡單**。

---

## 📋 檢查清單

- [ ] 在 Firebase 專案 `shuttle-system-60d6a` 中添加服務帳號 `shuttle-system@shuttle-system-487204.iam.gserviceaccount.com`
- [ ] 授予 **Firebase Admin** 或 **Firebase Realtime Database Admin** 角色
- [ ] 確認服務帳號出現在 Firebase IAM 成員列表中
- [ ] 重新部署服務（或等待自動部署）
- [ ] 檢查日誌，確認不再出現 `UnauthenticatedError`

---

## 🔍 驗證步驟

### 1. 檢查 Firebase IAM 設置

前往 Firebase Console：
- https://console.firebase.google.com/project/shuttle-system-60d6a/settings/iam

確認服務帳號在成員列表中。

### 2. 檢查日誌

部署後，檢查日誌應該看到：
- ✅ `Firebase: Initialized path /sheet_locks`
- ✅ `Firebase: Initialized path /booking_seq`
- ❌ 不應該看到 `UnauthenticatedError`

---

## 🔗 相關連結

- Firebase IAM 設置：https://console.firebase.google.com/project/shuttle-system-60d6a/settings/iam
- Firebase Console：https://console.firebase.google.com/project/shuttle-system-60d6a
- GCP IAM：https://console.cloud.google.com/iam-admin/iam?project=shuttle-system-487204

---

## ⚠️ 重要提示

**Firebase 專案的 IAM 設置與 GCP 專案的 IAM 設置是分開的**！

即使服務帳號在 GCP 專案中有所有權限，如果沒有在 Firebase 專案中授予權限，仍然無法訪問 Firebase Realtime Database。

---

## 🎯 快速修復

1. 前往 Firebase Console IAM 設置
2. 添加服務帳號：`shuttle-system@shuttle-system-487204.iam.gserviceaccount.com`
3. 授予 **Firebase Admin** 角色
4. 保存更改
5. 等待自動部署或手動觸發部署

