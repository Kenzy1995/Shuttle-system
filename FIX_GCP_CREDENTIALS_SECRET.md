# 🔧 修復 GCP_CREDENTIALS Secret 錯誤

## ❌ 錯誤訊息

```
Error: google-github-actions/auth failed with: failed to parse service account key JSON credentials: unexpected token '', "W+-z"... is not valid JSON
```

這個錯誤表示 `GCP_CREDENTIALS` Secret 中的 JSON 格式不正確或已損壞。

---

## ✅ 解決方案

### 方法 1: 重新設置 GCP_CREDENTIALS Secret（推薦）

#### 步驟 1: 獲取正確的服務帳號 JSON

1. 前往 GCP Console: https://console.cloud.google.com/iam-admin/serviceaccounts?project=shuttle-system-487204
2. 找到服務帳號: `shuttle-system@shuttle-system-487204.iam.gserviceaccount.com`
3. 點擊服務帳號名稱
4. 點擊「金鑰」標籤
5. 點擊「新增金鑰」→「建立新金鑰」
6. 選擇「JSON」格式
7. 下載 JSON 檔案（例如：`shuttle-system-487204-xxxxx.json`）

#### 步驟 2: 驗證 JSON 格式

在本地打開下載的 JSON 檔案，確認格式正確：

```json
{
  "type": "service_account",
  "project_id": "shuttle-system-487204",
  "private_key_id": "...",
  "private_key": "-----BEGIN PRIVATE KEY-----\n...\n-----END PRIVATE KEY-----\n",
  "client_email": "shuttle-system@shuttle-system-487204.iam.gserviceaccount.com",
  "client_id": "...",
  "auth_uri": "https://accounts.google.com/o/oauth2/auth",
  "token_uri": "https://oauth2.googleapis.com/token",
  "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
  "client_x509_cert_url": "https://www.googleapis.com/robot/v1/metadata/x509/shuttle-system%40shuttle-system-487204.iam.gserviceaccount.com",
  "universe_domain": "googleapis.com"
}
```

**重要檢查點**:
- ✅ 必須以 `{` 開始，以 `}` 結束
- ✅ 所有字串必須用雙引號 `"` 包圍
- ✅ `private_key` 中的換行符必須是 `\n`（不是實際的換行）
- ✅ 不能有多餘的逗號
- ✅ 不能有註解

#### 步驟 3: 複製完整 JSON 內容

**Windows (PowerShell)**:
```powershell
# 讀取 JSON 檔案內容
$content = Get-Content -Path "shuttle-system-487204-xxxxx.json" -Raw
# 複製到剪貼板
$content | Set-Clipboard
```

**Windows (CMD)**:
```cmd
# 使用記事本打開檔案，全選 (Ctrl+A)，複製 (Ctrl+C)
notepad shuttle-system-487204-xxxxx.json
```

**Mac/Linux**:
```bash
# 複製 JSON 內容到剪貼板
cat shuttle-system-487204-xxxxx.json | pbcopy  # Mac
cat shuttle-system-487204-xxxxx.json | xclip -selection clipboard  # Linux
```

#### 步驟 4: 更新 GitHub Secret

1. 前往: https://github.com/Kenzy1995/Shuttle-system/settings/secrets/actions
2. 找到 `GCP_CREDENTIALS` Secret
3. 點擊「更新」
4. **重要**: 在 Value 欄位中：
   - 直接貼上 JSON 內容（不要添加額外的引號）
   - 不要添加 `json:` 前綴
   - 不要添加任何註解
   - 確保是完整的 JSON 物件（從 `{` 到 `}`）
5. 點擊「更新 secret」

#### 步驟 5: 驗證設置

使用以下方法驗證 JSON 格式：

**在本地驗證**:
```bash
# 使用 Python 驗證 JSON
python -m json.tool shuttle-system-487204-xxxxx.json

# 或使用 Node.js
node -e "console.log(JSON.parse(require('fs').readFileSync('shuttle-system-487204-xxxxx.json', 'utf8')))"
```

如果沒有錯誤，JSON 格式正確。

---

### 方法 2: 使用 Base64 編碼（如果方法 1 失敗）

如果直接貼上 JSON 仍有問題，可以嘗試使用 Base64 編碼：

#### 步驟 1: 編碼 JSON 檔案

**Windows (PowerShell)**:
```powershell
$content = Get-Content -Path "shuttle-system-487204-xxxxx.json" -Raw -Encoding UTF8
$bytes = [System.Text.Encoding]::UTF8.GetBytes($content)
$base64 = [System.Convert]::ToBase64String($bytes)
$base64 | Set-Clipboard
```

**Mac/Linux**:
```bash
base64 -i shuttle-system-487204-xxxxx.json | pbcopy  # Mac
base64 shuttle-system-487204-xxxxx.json | xclip -selection clipboard  # Linux
```

#### 步驟 2: 更新工作流程

需要修改工作流程以解碼 Base64：

```yaml
- name: Authenticate to Google Cloud
  uses: google-github-actions/auth@v2
  with:
    credentials_json: ${{ secrets.GCP_CREDENTIALS_BASE64 }}
```

然後在認證步驟前添加解碼步驟：

```yaml
- name: Decode GCP Credentials
  run: |
    echo '${{ secrets.GCP_CREDENTIALS_BASE64 }}' | base64 -d > $HOME/gcp-key.json
  shell: bash

- name: Authenticate to Google Cloud
  uses: google-github-actions/auth@v2
  with:
    credentials_json: ${{ github.workspace }}/gcp-key.json
```

**注意**: 這個方法較複雜，建議先嘗試方法 1。

---

## 🔍 常見問題排查

### 問題 1: JSON 包含不可見字符

**解決方案**:
1. 使用純文字編輯器（如 Notepad++、VS Code）打開 JSON 檔案
2. 顯示所有字符（在 VS Code 中：View → Render Whitespace）
3. 刪除任何不可見字符
4. 重新複製

### 問題 2: 換行符問題

**解決方案**:
- 確保 `private_key` 中的換行符是 `\n`（反斜線 + n）
- 不是實際的換行符
- 例如：`"-----BEGIN PRIVATE KEY-----\nMIIEvQIBADANBgkqhkiG9w0BAQEFAASCBKcwggSjAgEAAoIBAQDcpKRVmJ6Fv13n\n..."`

### 問題 3: 編碼問題

**解決方案**:
- 確保 JSON 檔案使用 UTF-8 編碼
- 在 VS Code 中：右下角顯示編碼，點擊選擇「UTF-8」
- 重新保存檔案

### 問題 4: 多餘的引號或轉義

**解決方案**:
- GitHub Secret 的 Value 欄位中，直接貼上 JSON 內容
- 不要手動添加外層引號
- 不要轉義內部引號

---

## ✅ 驗證設置是否正確

設置完成後，重新觸發 GitHub Actions 工作流程：

1. 前往: https://github.com/Kenzy1995/Shuttle-system/actions
2. 點擊失敗的工作流程
3. 點擊「Re-run jobs」
4. 查看「Authenticate to Google Cloud」步驟是否成功

如果仍然失敗，請檢查：
- JSON 格式是否正確（使用驗證工具）
- 是否包含完整的 JSON 物件
- 是否有不可見字符

---

## 📝 正確的 JSON 範例格式

**重要**: 以下只是格式範例，請使用您從 GCP Console 下載的實際 JSON 檔案內容。

```json
{
  "type": "service_account",
  "project_id": "shuttle-system-487204",
  "private_key_id": "YOUR_PRIVATE_KEY_ID",
  "private_key": "-----BEGIN PRIVATE KEY-----\nYOUR_PRIVATE_KEY_CONTENT\n-----END PRIVATE KEY-----\n",
  "client_email": "shuttle-system@shuttle-system-487204.iam.gserviceaccount.com",
  "client_id": "YOUR_CLIENT_ID",
  "auth_uri": "https://accounts.google.com/o/oauth2/auth",
  "token_uri": "https://oauth2.googleapis.com/token",
  "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
  "client_x509_cert_url": "https://www.googleapis.com/robot/v1/metadata/x509/shuttle-system%40shuttle-system-487204.iam.gserviceaccount.com",
  "universe_domain": "googleapis.com"
}
```

**注意**: 
- 請使用您從 GCP Console 下載的實際 JSON 檔案內容
- 不要使用範例中的佔位符（YOUR_PRIVATE_KEY_ID 等）
- 確保 `private_key` 中的換行符是 `\n`（不是實際換行）

---

## 🔗 相關連結

- GitHub Secrets: https://github.com/Kenzy1995/Shuttle-system/settings/secrets/actions
- GCP 服務帳號: https://console.cloud.google.com/iam-admin/serviceaccounts?project=shuttle-system-487204
- 創建新金鑰: https://console.cloud.google.com/iam-admin/serviceaccounts?project=shuttle-system-487204

