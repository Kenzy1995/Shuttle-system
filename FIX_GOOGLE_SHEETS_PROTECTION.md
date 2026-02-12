# 🔧 修復 Google Sheets 保護問題

## ❌ 問題診斷

從日誌中看到錯誤：
```
APIError: [400]: You are trying to edit a protected cell or object. Please contact the spreadsheet owner to remove protection if you need to edit.
```

**根本原因**：Google Sheets 中有某些單元格或範圍被保護，服務帳號無法寫入。

---

## ✅ 解決方案

### 步驟 1: 檢查 Google Sheets 保護設置

1. **打開 Google Sheets**：
   - https://docs.google.com/spreadsheets/d/1o_kLeuwP5_G08YYLlZKIgcYzlU1NIZD5SQnHoO59YUw

2. **檢查保護設置**：
   - 點擊「資料」→「保護的工作表和範圍」
   - 查看是否有保護的範圍

3. **檢查工作表保護**：
   - 右鍵點擊工作表標籤「預約審核(櫃台)」
   - 選擇「保護工作表」
   - 查看是否有保護設置

### 步驟 2: 移除保護或授予權限

#### 選項 1: 移除保護（如果不需要保護）

1. **移除範圍保護**：
   - 點擊「資料」→「保護的工作表和範圍」
   - 找到保護的範圍
   - 點擊「移除」或「刪除」

2. **移除工作表保護**：
   - 右鍵點擊工作表標籤「預約審核(櫃台)」
   - 選擇「保護工作表」
   - 點擊「移除保護」

#### 選項 2: 授予服務帳號編輯權限（如果需要保留保護）

1. **添加服務帳號到保護範圍**：
   - 點擊「資料」→「保護的工作表和範圍」
   - 找到保護的範圍
   - 點擊「編輯」
   - 在「編輯者」中添加：`shuttle-system@shuttle-system-487204.iam.gserviceaccount.com`
   - 授予「編輯者」權限

2. **添加服務帳號到工作表保護**：
   - 右鍵點擊工作表標籤「預約審核(櫃台)」
   - 選擇「保護工作表」
   - 點擊「編輯」
   - 在「編輯者」中添加：`shuttle-system@shuttle-system-487204.iam.gserviceaccount.com`
   - 授予「編輯者」權限

---

## 📋 檢查清單

- [ ] 檢查 Google Sheets 是否有保護的範圍
- [ ] 檢查工作表「預約審核(櫃台)」是否有保護
- [ ] 移除保護或授予服務帳號編輯權限
- [ ] 確認服務帳號 `shuttle-system@shuttle-system-487204.iam.gserviceaccount.com` 有編輯權限
- [ ] 測試預約功能

---

## 🔍 驗證步驟

### 1. 檢查保護設置

在 Google Sheets 中確認：
- 沒有保護的範圍阻止寫入
- 工作表沒有保護阻止追加行

### 2. 測試預約功能

完成修復後，嘗試進行一次預約，確認：
- ✅ 不再出現 `APIError: [400]` 錯誤
- ✅ 預約數據成功寫入 Google Sheets

---

## 🔗 相關連結

- Google Sheets：https://docs.google.com/spreadsheets/d/1o_kLeuwP5_G08YYLlZKIgcYzlU1NIZD5SQnHoO59YUw
- 保護設置：在 Google Sheets 中點擊「資料」→「保護的工作表和範圍」

---

## ⚠️ 重要提示

1. **保護設置可能影響多個工作表**：檢查所有相關工作表的保護設置
2. **服務帳號權限**：確保服務帳號在保護範圍中有編輯權限
3. **測試環境隔離**：如果這是測試環境的 Google Sheets，確保與正式環境的保護設置一致

---

## 🎯 快速修復

1. 打開 Google Sheets
2. 檢查「資料」→「保護的工作表和範圍」
3. 移除所有保護或授予服務帳號編輯權限
4. 測試預約功能

