# 🔧 修復 Google Sheets API 權限問題

## ❌ 問題診斷

從日誌中發現：

```
RuntimeError: 無法開啟工作表「預約審核(櫃台)」: APIError: [500]: Internal error encountered.
```

這是 **Google Sheets API 權限問題**，不是 Firebase 問題。

---

## 🔍 根本原因

服務帳號 `shuttle-system@shuttle-system-487204.iam.gserviceaccount.com` 無法訪問 Google Sheets，可能因為：

1. **服務帳號沒有 Google Sheets 權限**
2. **Google Sheets 沒有共享給服務帳號**
3. **API 未啟用**

---

## ✅ 解決方案

### 步驟 1: 確認 Google Sheets API 已啟用

```bash
# 檢查 Google Sheets API 是否已啟用
gcloud services list --enabled --project=shuttle-system-487204 | grep sheets
```

如果沒有啟用，啟用它：
```bash
gcloud services enable sheets.googleapis.com --project=shuttle-system-487204
```

### 步驟 2: 授予服務帳號 Google Sheets 權限

```bash
# 授予服務帳號 Google Sheets 權限
gcloud projects add-iam-policy-binding shuttle-system-487204 \
  --member="serviceAccount:shuttle-system@shuttle-system-487204.iam.gserviceaccount.com" \
  --role="roles/sheets.admin"
```

或者更具體的權限：
```bash
# 授予 Google Drive API 權限（用於訪問 Google Sheets）
gcloud projects add-iam-policy-binding shuttle-system-487204 \
  --member="serviceAccount:shuttle-system@shuttle-system-487204.iam.gserviceaccount.com" \
  --role="roles/drive.file"
```

### 步驟 3: 在 Google Sheets 中共享給服務帳號

**這是最重要的步驟**：

1. **打開 Google Sheets**：
   - https://docs.google.com/spreadsheets/d/1o_kLeuwP5_G08YYLlZKIgcYzlU1NIZD5SQnHoO59YUw

2. **點擊右上角的「共享」按鈕**

3. **添加服務帳號**：
   - 輸入：`shuttle-system@shuttle-system-487204.iam.gserviceaccount.com`
   - 選擇權限：**編輯者** 或 **查看者**（根據需要）
   - 點擊「發送」

4. **確認共享**：
   - 服務帳號應該出現在共享列表中

---

## 📋 檢查清單

- [ ] Google Sheets API 已啟用
- [ ] 服務帳號有 `roles/sheets.admin` 或 `roles/drive.file` 權限
- [ ] Google Sheets 已共享給服務帳號
- [ ] 服務帳號可以訪問 Google Sheets

---

## 🔍 驗證步驟

### 1. 檢查服務帳號權限

```bash
gcloud projects get-iam-policy shuttle-system-487204 \
  --flatten="bindings[].members" \
  --filter="bindings.members:serviceAccount:shuttle-system@shuttle-system-487204.iam.gserviceaccount.com" \
  --format="table(bindings.role)"
```

### 2. 檢查 Google Sheets 共享設置

前往 Google Sheets 並確認服務帳號在共享列表中：
- https://docs.google.com/spreadsheets/d/1o_kLeuwP5_G08YYLlZKIgcYzlU1NIZD5SQnHoO59YUw

### 3. 測試 API 訪問

部署完成後，檢查日誌是否還有 `APIError: [500]` 錯誤。

---

## 🔗 相關連結

- Google Sheets：https://docs.google.com/spreadsheets/d/1o_kLeuwP5_G08YYLlZKIgcYzlU1NIZD5SQnHoO59YUw
- GCP IAM：https://console.cloud.google.com/iam-admin/iam?project=shuttle-system-487204
- API 啟用：https://console.cloud.google.com/apis/library?project=shuttle-system-487204

---

## ⚠️ 重要提示

**Google Sheets 共享是最關鍵的步驟**！

即使服務帳號有所有 GCP IAM 權限，如果 Google Sheets 沒有共享給服務帳號，仍然無法訪問。

---

## 🎯 快速修復命令

```bash
# 設置專案
gcloud config set project shuttle-system-487204

# 啟用 Google Sheets API
gcloud services enable sheets.googleapis.com --project=shuttle-system-487204

# 授予服務帳號 Google Sheets 權限
gcloud projects add-iam-policy-binding shuttle-system-487204 \
  --member="serviceAccount:shuttle-system@shuttle-system-487204.iam.gserviceaccount.com" \
  --role="roles/sheets.admin"

# 授予 Google Drive API 權限
gcloud projects add-iam-policy-binding shuttle-system-487204 \
  --member="serviceAccount:shuttle-system@shuttle-system-487204.iam.gserviceaccount.com" \
  --role="roles/drive.file"
```

**然後記得在 Google Sheets 中共享給服務帳號！**

