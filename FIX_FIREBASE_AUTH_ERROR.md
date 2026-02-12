# 🔧 修復 Firebase 認證錯誤

## ❌ 問題診斷

從日誌中發現以下錯誤：

1. **Firebase 認證失敗**：
   ```
   UnauthenticatedError msg=Unauthorized request.
   ```

2. **容量鎖定超時**：
   ```
   [cap_lock] timeout lock_id=cap_807d18e2036e9a222a02ba2c holder=a4cae39eb5aa1349 waited_ms=60209
   ```

3. **預約請求失敗**：
   ```
   "POST /api/ops HTTP/1.1" 503
   ```

## 🔍 根本原因

`booking-manager` 服務使用 Firebase Realtime Database 來實現併發鎖定機制（防止超賣）。但是 Firebase 初始化失敗，導致：

1. 無法獲取容量鎖定
2. 鎖定超時（60秒）
3. 預約請求返回 503 錯誤

## 🔧 解決方案

### 方案 1: 確認 GitHub Secrets 設置

確保在 GitHub Secrets 中設置了 `FIREBASE_RTDB_URL`：

1. 前往 GitHub 倉庫：https://github.com/Kenzy1995/Shuttle-system
2. 進入 **Settings** → **Secrets and variables** → **Actions**
3. 確認 `FIREBASE_RTDB_URL` 的值為：
   ```
   https://shuttle-system-60d6a-default-rtdb.asia-southeast1.firebasedatabase.app/
   ```

### 方案 2: 確認服務帳號權限

確保服務帳號 `shuttle-system@shuttle-system-487204.iam.gserviceaccount.com` 有 Firebase 權限：

```bash
# 檢查服務帳號是否有 Firebase 權限
gcloud projects get-iam-policy shuttle-system-487204 \
  --flatten="bindings[].members" \
  --filter="bindings.members:serviceAccount:shuttle-system@shuttle-system-487204.iam.gserviceaccount.com" \
  --format="table(bindings.role)"
```

### 方案 3: 更新 Firebase 初始化代碼（改進錯誤處理）

當前代碼在 Firebase 初始化失敗時只返回 `False`，沒有記錄詳細錯誤。建議改進錯誤處理：

```python
def _init_firebase():
    """初始化 Firebase Admin SDK（用於併發鎖）"""
    try:
        if not firebase_admin._apps:
            service_account_path = "service_account.json"
            if os.path.exists(service_account_path):
                cred = credentials.Certificate(service_account_path)
            else:
                cred = credentials.ApplicationDefault()
            db_url = os.environ.get("FIREBASE_RTDB_URL")
            if not db_url:
                project_id = os.environ.get("GOOGLE_CLOUD_PROJECT", "shuttle-system-60d6a")
                db_url = f"https://{project_id}-default-rtdb.asia-southeast1.firebasedatabase.app/"
            firebase_admin.initialize_app(cred, {"databaseURL": db_url})
        return True
    except Exception as e:
        log.error(f"Firebase initialization failed: {type(e).__name__}: {str(e)}")
        return False
```

## ✅ 驗證步驟

1. **檢查環境變數**：
   ```bash
   gcloud run services describe booking-manager \
     --region=asia-east1 \
     --project=shuttle-system-487204 \
     --format="value(spec.template.spec.containers[0].env)"
   ```

2. **檢查服務日誌**：
   ```bash
   gcloud run services logs read booking-manager \
     --region=asia-east1 \
     --project=shuttle-system-487204 \
     --limit=50
   ```

3. **測試 Firebase 連接**：
   訪問服務的健康檢查端點，查看是否有 Firebase 相關錯誤。

## 📋 檢查清單

- [ ] 確認 `FIREBASE_RTDB_URL` GitHub Secret 已設置
- [ ] 確認服務帳號有 Firebase 權限
- [ ] 確認 Cloud Run 服務的環境變數已正確設置
- [ ] 檢查 Firebase 專案是否正確（`shuttle-system-60d6a`）
- [ ] 確認 Firebase Realtime Database 已啟用

## 🔗 相關連結

- Firebase Console: https://console.firebase.google.com/project/shuttle-system-60d6a
- Cloud Run 服務: https://console.cloud.google.com/run?project=shuttle-system-487204
- GitHub Secrets: https://github.com/Kenzy1995/Shuttle-system/settings/secrets/actions

