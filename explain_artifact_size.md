# Artifact Registry 容量大的原因與解決方案

## 為什麼容量依然很大？

### 1. Docker 層級共享技術
Docker 映像使用**層級（Layer）共享**技術：
- 多個映像可能共享相同的底層（base image、依賴套件等）
- 即使刪除了映像，共享的層級可能仍然存在
- 只有當**所有使用該層級的映像都被刪除**時，該層級才會被清理

### 2. GCP 的清理機制
- GCP 不會立即刪除未使用的層級
- 需要等待 **24-48 小時** 讓系統自動清理
- 這是為了防止誤刪和提供恢復時間

### 3. 實際情況分析
根據檢查結果：
- **hotel-web**: 已刪除 2 個舊映像，保留 1 個正在使用的
- **booking-api**: 只有 1 個映像，但被 5 個 revisions 使用
- **booking-manager**: 只有 1 個映像，但被 5 個 revisions 使用
- **driver-api2**: 只有 1 個映像，但被 5 個 revisions 使用

## 已實施的安全措施

✅ **確保不會刪除正在使用的映像**
- 腳本會檢查所有 Cloud Run revisions 使用的映像
- 只刪除完全未使用的映像

✅ **確保服務網址不會改變**
- 刪除映像不會影響 Cloud Run 服務配置
- 服務 URL 保持不變

✅ **確保服務運行不受影響**
- 只刪除未使用的映像
- 正在運行的服務使用的映像完全保留

## 進一步優化建議

### 1. 清理舊的 Cloud Run Revisions
雖然我們已經在 GitHub Actions 中添加了自動清理，但可以手動清理：

```bash
# 查看所有 revisions
gcloud run revisions list --service=booking-api --region=asia-east1 --project=forte-booking-system

# 只保留最新的 1 個 revision（已通過 GitHub Actions 自動化）
```

### 2. 等待 GCP 自動清理
- 等待 **24-48 小時** 後再檢查容量
- GCP 會自動清理未使用的 Docker 層級

### 3. 定期執行清理腳本
可以定期執行 `auto_cleanup_artifact_final.py` 來清理未使用的映像

### 4. 檢查其他倉庫
如果有其他 Artifact Registry 倉庫，也需要檢查：

```bash
gcloud artifacts repositories list --project=forte-booking-system
```

## 驗證清理效果

### 檢查當前使用的映像
```bash
# 檢查 hotel-web
gcloud run services describe hotel-web --region=asia-east1 --format="value(spec.template.spec.containers[0].image)" --project=forte-booking-system

# 檢查所有服務
gcloud run services list --region=asia-east1 --project=forte-booking-system --format="table(metadata.name,status.url)"
```

### 檢查 Artifact Registry 容量
在 Cloud Console 中：
1. 前往 Artifact Registry
2. 查看倉庫大小
3. 等待 24-48 小時後再次檢查

## 總結

✅ **已完成**：
- 刪除了 2 個未使用的 hotel-web 映像
- 確保所有正在使用的映像都被保護
- 服務網址和運行狀態不受影響

⏳ **需要等待**：
- GCP 自動清理未使用的 Docker 層級（24-48 小時）

💡 **建議**：
- 定期執行清理腳本
- 監控 Artifact Registry 容量變化
- 繼續使用 GitHub Actions 自動清理功能

