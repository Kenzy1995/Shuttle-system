# ✅ 自動初始化 Firebase 路徑（已修復）

## 🔧 修復內容

已恢復舊版本的自動初始化行為，後端現在會在啟動時自動創建必要的 Firebase 路徑。

---

## 📝 修改內容

### 1. 添加自動初始化函數

在 `_init_firebase()` 函數中添加了 `_ensure_firebase_paths()` 調用：

```python
def _ensure_firebase_paths():
    """確保 Firebase 必要的路徑存在（自動初始化）"""
    try:
        paths = ["/sheet_locks", "/booking_seq"]
        for path in paths:
            ref = db.reference(path)
            snapshot = ref.get()
            if snapshot is None:
                ref.set({})
                log.info(f"Firebase: Initialized path {path}")
    except Exception as e:
        log.warning(f"Firebase: Failed to ensure paths: {type(e).__name__}: {str(e)}")
```

### 2. 添加啟動事件處理器

在 FastAPI 應用啟動時自動初始化：

```python
@app.on_event("startup")
async def startup_event():
    """應用啟動時自動初始化 Firebase 路徑"""
    log.info("Application startup: Ensuring Firebase paths exist")
    _init_firebase()
```

---

## ✅ 行為恢復

現在的行為與舊版本一致：
- ✅ **自動初始化**：應用啟動時自動檢查並創建必要的路徑
- ✅ **無需手動操作**：不需要在 Firebase Console 中手動創建路徑
- ✅ **A/B 測試一致性**：新環境和舊環境行為一致

---

## 🔍 工作原理

1. **應用啟動時**：`startup_event()` 被調用
2. **初始化 Firebase**：`_init_firebase()` 被調用
3. **檢查路徑**：`_ensure_firebase_paths()` 檢查 `/sheet_locks` 和 `/booking_seq` 是否存在
4. **自動創建**：如果路徑不存在，自動創建空對象 `{}`

---

## 📋 驗證步驟

部署後，檢查日誌應該看到：
- `Application startup: Ensuring Firebase paths exist`
- `Firebase: Initialized path /sheet_locks`（如果路徑不存在）
- `Firebase: Initialized path /booking_seq`（如果路徑不存在）

---

## 🎯 總結

現在後端會自動初始化 Firebase 路徑，與舊版本行為一致，無需手動操作。

