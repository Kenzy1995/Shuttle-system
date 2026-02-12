# 🔍 診斷鎖定超時問題

## ✅ 當前狀態

從最新日誌看到：
- ✅ **Firebase 初始化成功**：`Firebase: Initialization successful`
- ✅ **沒有認證錯誤**：不再出現 `UnauthenticatedError`
- ⚠️ **鎖定超時**：`[cap_lock] timeout`（60秒後）

---

## 🔍 問題分析

### 鎖定超時的可能原因

1. **鎖定被其他實例持有**
   - 可能有其他 Cloud Run 實例正在使用同一個鎖定
   - 鎖定沒有正確釋放

2. **鎖定過期時間設置問題**
   - `LOCK_STALE_SECONDS = 30`（30秒過期）
   - 但鎖定等待時間是 60 秒
   - 如果鎖定在 30 秒內沒有更新，應該被視為過期

3. **Firebase 交易失敗**
   - 雖然沒有看到 `UnauthenticatedError`，但交易可能仍然失敗
   - 需要檢查是否有其他錯誤

---

## 🔧 診斷步驟

### 1. 檢查 Firebase 中的鎖定狀態

訪問 Firebase Console 查看當前鎖定狀態：
- https://console.firebase.google.com/project/shuttle-system-60d6a/database/shuttle-system-60d6a-default-rtdb/data/~2Fsheet_locks

查看是否有鎖定被卡住：
- 檢查 `cap_807d18e2036e9a222a02ba2c` 鎖定的狀態
- 如果鎖定存在且 `ts` 時間戳很舊，可能是卡住的鎖定

### 2. 檢查是否有其他實例

檢查 Cloud Run 服務的實例數量：
```bash
gcloud run services describe booking-manager \
  --region=asia-east1 \
  --project=shuttle-system-487204 \
  --format="value(status.conditions)"
```

### 3. 檢查鎖定邏輯

從代碼看，鎖定邏輯應該：
1. 嘗試獲取鎖定（如果不存在或已過期）
2. 如果鎖定被其他實例持有，輪詢等待
3. 如果鎖定在 30 秒內沒有更新，視為過期並獲取

但日誌中沒有看到 `poll` 訊息，這可能表示：
- 交易一直失敗（但沒有錯誤訊息）
- 或者鎖定邏輯有問題

---

## 🔧 可能的解決方案

### 方案 1: 清理卡住的鎖定

如果 Firebase 中有卡住的鎖定，可以手動清理：

1. 前往 Firebase Console
2. 找到 `/sheet_locks/cap_807d18e2036e9a222a02ba2c`
3. 檢查 `ts` 時間戳
4. 如果時間戳很舊（超過 30 秒），刪除該鎖定

### 方案 2: 檢查規則設置

確認規則設置為與舊版本一致（`false`），因為：
- Firebase Admin SDK 會繞過規則
- 規則不應該影響 Admin SDK 的訪問

### 方案 3: 檢查服務帳號權限

雖然已經授予了 `roles/firebase.admin`，但可能需要更具體的權限：

```bash
# 檢查服務帳號是否有 Firebase Realtime Database Admin 權限
gcloud projects get-iam-policy shuttle-system-487204 \
  --flatten="bindings[].members" \
  --filter="bindings.members:serviceAccount:shuttle-system@shuttle-system-487204.iam.gserviceaccount.com" \
  --format="table(bindings.role)"
```

---

## 📋 檢查清單

- [ ] 確認 Firebase 規則設置為與舊版本一致（`false`）
- [ ] 檢查 Firebase 中是否有卡住的鎖定
- [ ] 檢查服務帳號權限是否完整
- [ ] 檢查是否有其他 Cloud Run 實例持有鎖定
- [ ] 檢查鎖定邏輯是否正確

---

## 🔗 相關連結

- Firebase Console：https://console.firebase.google.com/project/shuttle-system-60d6a/database/shuttle-system-60d6a-default-rtdb/data
- Cloud Run 服務：https://console.cloud.google.com/run?project=shuttle-system-487204

