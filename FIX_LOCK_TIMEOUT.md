# 🔧 修復鎖定超時問題

## ❌ 問題診斷

從日誌中看到：
- ✅ Firebase 初始化成功：`Firebase: Initialization successful`
- ✅ 沒有 Google Sheets API 錯誤（已修復）
- ⚠️ **鎖定超時**：`[cap_lock] timeout`（60秒後）
- ❌ 503 錯誤：請求超時

---

## 🔍 根本原因

鎖定超時表示 Firebase 交易無法成功獲取鎖定。可能的原因：

1. **Firebase 交易靜默失敗**：交易沒有拋出異常，但也沒有成功
2. **鎖定被其他實例持有**：可能有其他 Cloud Run 實例持有鎖定
3. **Firebase 規則問題**：雖然 Admin SDK 應該繞過規則，但可能仍有問題
4. **鎖定邏輯問題**：輪詢邏輯可能有問題

---

## ✅ 解決方案

### 方案 1: 檢查 Firebase 中的卡住鎖定

1. **前往 Firebase Console**：
   - https://console.firebase.google.com/project/shuttle-system-60d6a/database/shuttle-system-60d6a-default-rtdb/data/~2Fsheet_locks

2. **檢查鎖定狀態**：
   - 查看是否有 `cap_807d18e2036e9a222a02ba2c` 鎖定
   - 檢查 `ts` 時間戳
   - 如果時間戳很舊（超過 30 秒），可能是卡住的鎖定

3. **清理卡住的鎖定**：
   - 如果發現卡住的鎖定，手動刪除它
   - 或者等待 30 秒後，鎖定應該自動過期

### 方案 2: 檢查 Firebase 規則

確認規則設置為與舊版本一致：

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

### 方案 3: 檢查是否有其他實例

檢查 Cloud Run 服務的實例數量：

```bash
gcloud run services describe booking-manager \
  --region=asia-east1 \
  --project=shuttle-system-487204 \
  --format="value(status.conditions)"
```

### 方案 4: 改進鎖定邏輯（如果需要）

如果問題持續，可能需要改進鎖定邏輯，添加更多日誌來診斷問題。

---

## 🔍 診斷步驟

### 1. 檢查 Firebase 鎖定狀態

前往 Firebase Console 並檢查：
- https://console.firebase.google.com/project/shuttle-system-60d6a/database/shuttle-system-60d6a-default-rtdb/data/~2Fsheet_locks

### 2. 檢查日誌中的 poll 訊息

從日誌中應該看到 `[cap_lock] poll=...` 訊息，如果沒有看到，表示交易可能靜默失敗。

### 3. 檢查 Firebase 規則

確認規則設置為與舊版本一致（`false`）。

---

## 📋 檢查清單

- [ ] 檢查 Firebase 中是否有卡住的鎖定
- [ ] 確認 Firebase 規則設置為與舊版本一致
- [ ] 檢查是否有其他 Cloud Run 實例持有鎖定
- [ ] 檢查日誌中是否有 poll 訊息

---

## 🔗 相關連結

- Firebase Console：https://console.firebase.google.com/project/shuttle-system-60d6a/database/shuttle-system-60d6a-default-rtdb/data
- Cloud Run 服務：https://console.cloud.google.com/run?project=shuttle-system-487204

---

## ⚠️ 重要提示

**Firebase Admin SDK 會繞過安全規則**，所以規則設置為 `false` 不應該影響鎖定功能。

如果鎖定仍然超時，問題可能在於：
1. 鎖定被其他實例持有
2. Firebase 交易靜默失敗
3. 鎖定邏輯本身的問題

