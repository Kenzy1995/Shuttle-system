# 🔐 授予 Firebase 權限

## ❌ 問題確認

日誌顯示大量 `UnauthenticatedError msg=Unauthorized request.` 錯誤，這是 **Firebase Realtime Database 權限問題**。

服務帳號 `shuttle-system@shuttle-system-487204.iam.gserviceaccount.com` 無法訪問 Firebase Realtime Database。

---

## 🔧 解決方案

### 方法 1: 在 Firebase Console 中設置規則（推薦）

1. **前往 Firebase Console**：
   - https://console.firebase.google.com/project/shuttle-system-60d6a/database/shuttle-system-60d6a-default-rtdb/rules

2. **更新 Realtime Database 規則**：
   將規則設置為允許服務帳號訪問：

   ```json
   {
     "rules": {
       "booking_seq": {
         ".read": "auth != null",
         ".write": "auth != null"
       },
       "cap_lock": {
         ".read": "auth != null",
         ".write": "auth != null"
       },
       ".read": "auth != null",
       ".write": "auth != null"
     }
   }
   ```

3. **點擊「發布」**保存規則

### 方法 2: 使用 gcloud 命令授予權限

執行以下命令授予服務帳號 Firebase 權限：

```bash
# 設置專案
gcloud config set project shuttle-system-487204

# 授予服務帳號 Firebase Admin 角色（如果需要的話）
gcloud projects add-iam-policy-binding shuttle-system-487204 \
  --member="serviceAccount:shuttle-system@shuttle-system-487204.iam.gserviceaccount.com" \
  --role="roles/firebase.admin"

# 或者授予更具體的權限
gcloud projects add-iam-policy-binding shuttle-system-487204 \
  --member="serviceAccount:shuttle-system@shuttle-system-487204.iam.gserviceaccount.com" \
  --role="roles/datastore.user"
```

### 方法 3: 在 Firebase Console 中添加服務帳號

1. **前往 Firebase Console**：
   - https://console.firebase.google.com/project/shuttle-system-60d6a/settings/iam

2. **添加服務帳號**：
   - 點擊「添加成員」
   - 輸入服務帳號：`shuttle-system@shuttle-system-487204.iam.gserviceaccount.com`
   - 選擇角色：**Firebase Admin SDK Administrator Service Agent** 或 **Firebase Realtime Database Admin**
   - 點擊「添加」

---

## ✅ 驗證步驟

### 1. 檢查服務帳號權限

```bash
# 檢查服務帳號的 IAM 角色
gcloud projects get-iam-policy shuttle-system-487204 \
  --flatten="bindings[].members" \
  --filter="bindings.members:serviceAccount:shuttle-system@shuttle-system-487204.iam.gserviceaccount.com" \
  --format="table(bindings.role)"
```

### 2. 檢查 Firebase 規則

訪問 Firebase Console 確認規則已更新：
- https://console.firebase.google.com/project/shuttle-system-60d6a/database/shuttle-system-60d6a-default-rtdb/rules

### 3. 測試預約功能

部署完成後，嘗試進行預約，檢查日誌是否還有 `UnauthenticatedError` 錯誤。

---

## 📋 快速修復命令

複製並執行以下命令來快速授予權限：

```bash
# 設置專案
gcloud config set project shuttle-system-487204

# 授予 Firebase Admin 權限
gcloud projects add-iam-policy-binding shuttle-system-487204 \
  --member="serviceAccount:shuttle-system@shuttle-system-487204.iam.gserviceaccount.com" \
  --role="roles/firebase.admin"

# 驗證權限
gcloud projects get-iam-policy shuttle-system-487204 \
  --flatten="bindings[].members" \
  --filter="bindings.members:serviceAccount:shuttle-system@shuttle-system-487204.iam.gserviceaccount.com" \
  --format="table(bindings.role)"
```

---

## 🔗 相關連結

- Firebase Console: https://console.firebase.google.com/project/shuttle-system-60d6a
- Firebase Realtime Database 規則: https://console.firebase.google.com/project/shuttle-system-60d6a/database/shuttle-system-60d6a-default-rtdb/rules
- Firebase IAM 設置: https://console.firebase.google.com/project/shuttle-system-60d6a/settings/iam
- GCP IAM: https://console.cloud.google.com/iam-admin/iam?project=shuttle-system-487204

---

## ⚠️ 注意事項

1. **Firebase 專案 ID**：確保使用正確的 Firebase 專案 ID `shuttle-system-60d6a`
2. **GCP 專案 ID**：確保使用正確的 GCP 專案 ID `shuttle-system-487204`
3. **服務帳號**：確保服務帳號名稱正確 `shuttle-system@shuttle-system-487204.iam.gserviceaccount.com`

---

## 🎯 預期結果

修復後，日誌中應該不再出現 `UnauthenticatedError` 錯誤，預約功能應該可以正常工作。

