# ✅ 驗證測試環境配置

## 🔍 當前配置檢查

### GCP 專案
- **專案 ID**：`shuttle-system-487204`
- **服務帳號**：`shuttle-system@shuttle-system-487204.iam.gserviceaccount.com`

### Firebase 專案
- **專案 ID**：`shuttle-system-60d6a`
- **Firebase Realtime Database URL**：`https://shuttle-system-60d6a-default-rtdb.asia-southeast1.firebasedatabase.app/`

### Firebase IAM 權限
根據您提供的信息，Firebase 專案中有：
- `firebase-adminsdk-fbsvc@shuttle-system-60d6a.iam.gserviceaccount.com`（Firebase 自動創建的服務帳號）

---

## ❌ 問題診斷

**關鍵問題**：測試環境使用的服務帳號 `shuttle-system@shuttle-system-487204.iam.gserviceaccount.com` **沒有在 Firebase 專案 `shuttle-system-60d6a` 中被授予權限**。

Firebase 專案中只有 `firebase-adminsdk-fbsvc@shuttle-system-60d6a.iam.gserviceaccount.com`，但這是 Firebase 自動創建的服務帳號，不是測試環境使用的服務帳號。

---

## ✅ 解決方案

### 在 Firebase 專案中添加測試環境的服務帳號

1. **前往 Firebase Console IAM 設置**：
   - https://console.firebase.google.com/project/shuttle-system-60d6a/settings/iam

2. **添加服務帳號**：
   - 點擊「添加成員」或「Add member」
   - 輸入：`shuttle-system@shuttle-system-487204.iam.gserviceaccount.com`
   - 選擇角色：**Firebase Admin SDK Administrator Service Agent** 或 **Firebase Realtime Database Admin**
   - 點擊「添加」

3. **確認權限**：
   - 服務帳號應該出現在成員列表中
   - 應該有 **Firebase Admin SDK Administrator Service Agent** 或 **Firebase Realtime Database Admin** 角色

---

## 📋 完整配置檢查清單

### GCP 專案配置
- [x] GCP 專案 ID：`shuttle-system-487204`
- [x] 服務帳號：`shuttle-system@shuttle-system-487204.iam.gserviceaccount.com`
- [ ] 服務帳號有 Cloud Run 權限
- [ ] 服務帳號有 Artifact Registry 權限

### Firebase 專案配置
- [x] Firebase 專案 ID：`shuttle-system-60d6a`
- [x] Firebase Realtime Database URL：`https://shuttle-system-60d6a-default-rtdb.asia-southeast1.firebasedatabase.app/`
- [ ] **服務帳號 `shuttle-system@shuttle-system-487204.iam.gserviceaccount.com` 在 Firebase IAM 中**
- [ ] 服務帳號有 **Firebase Admin SDK Administrator Service Agent** 角色
- [x] Firebase 規則設置正確（與舊版本一致）

### GitHub Actions 配置
- [ ] `GCP_PROJECT_ID` = `shuttle-system-487204`
- [ ] `FIREBASE_RTDB_URL` = `https://shuttle-system-60d6a-default-rtdb.asia-southeast1.firebasedatabase.app/`
- [ ] `GCP_CREDENTIALS` 是 `shuttle-system@shuttle-system-487204.iam.gserviceaccount.com` 的 JSON 金鑰

### Cloud Run 配置
- [ ] 服務帳號設置為：`shuttle-system@shuttle-system-487204.iam.gserviceaccount.com`
- [ ] 環境變數 `FIREBASE_RTDB_URL` 設置正確

---

## 🔍 驗證步驟

### 1. 檢查 Firebase IAM

前往：
- https://console.firebase.google.com/project/shuttle-system-60d6a/settings/iam

確認 `shuttle-system@shuttle-system-487204.iam.gserviceaccount.com` 在成員列表中。

### 2. 檢查 GitHub Secrets

確認以下 Secrets 設置正確：
- `GCP_PROJECT_ID` = `shuttle-system-487204`
- `FIREBASE_RTDB_URL` = `https://shuttle-system-60d6a-default-rtdb.asia-southeast1.firebasedatabase.app/`
- `GCP_CREDENTIALS` = 服務帳號 JSON（`shuttle-system@shuttle-system-487204.iam.gserviceaccount.com`）

### 3. 檢查 Cloud Run 服務配置

確認所有服務的服務帳號設置為：
- `shuttle-system@shuttle-system-487204.iam.gserviceaccount.com`

### 4. 檢查日誌

部署後，檢查日誌應該看到：
- ✅ `Firebase: Initialization successful`
- ✅ `Firebase: Initialized path /sheet_locks`
- ✅ `Firebase: Initialized path /booking_seq`
- ❌ 不應該看到 `UnauthenticatedError`

---

## 🔗 相關連結

- Firebase IAM 設置：https://console.firebase.google.com/project/shuttle-system-60d6a/settings/iam
- Firebase Console：https://console.firebase.google.com/project/shuttle-system-60d6a
- GCP IAM：https://console.cloud.google.com/iam-admin/iam?project=shuttle-system-487204
- Cloud Run 服務：https://console.cloud.google.com/run?project=shuttle-system-487204

---

## ⚠️ 重要提示

**Firebase 專案的 IAM 設置與 GCP 專案的 IAM 設置是分開的**！

即使服務帳號在 GCP 專案中有所有權限，如果沒有在 Firebase 專案中授予權限，仍然無法訪問 Firebase Realtime Database。

---

## 🎯 快速修復

1. 前往 Firebase Console IAM 設置
2. 添加服務帳號：`shuttle-system@shuttle-system-487204.iam.gserviceaccount.com`
3. 授予 **Firebase Admin SDK Administrator Service Agent** 角色
4. 保存更改
5. 等待自動部署或手動觸發部署

