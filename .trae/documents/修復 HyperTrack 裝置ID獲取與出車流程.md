## 問題原因判斷
- 插件回傳 `{ deviceId: '' }`，後端 400 顯示 `device_id` 非 UUID，核心在「裝置未完成 SDK 註冊」。
- 可能成因：
  1. 發布金鑰讀取失敗（Manifest meta-data 未被讀到或 key 拼寫不符）
  2. SDK 未完成初始化/握手（未啟動追蹤或遭系統權限阻擋）
  3. 位置權限/背景定位權限未授權，導致 `start()` 無法建立會話
  4. 網路或防火牆阻擋到 HyperTrack 端點，首次握手失敗
  5. 插件方法只回 `ok` 不回錯誤細節，導致前端看不出初始化失敗

## 修復與驗證步驟（最少改動）
1. 在 Android 插件加強金鑰讀取與回報：
   - 啟動時印出讀到的 `HyperTrackPublishableKey`（前端 `console.log` 透過 Capacitor）
   - 若 key 讀不到或空字串，`getDeviceId()` 回 `{ deviceId: '' , error: 'missing_key' }`
2. 加入「一次握手」流程（前端）：
   - 依序請求權限：`ACCESS_FINE_LOCATION`、`ACCESS_COARSE_LOCATION`、`ACCESS_BACKGROUND_LOCATION`（Android 10+）
   - `setWorkerHandle` → `startTracking` → 等待 3 秒 → `getDeviceId` → `stopTracking`
   - 取得後寫入 `localStorage('hypertrack_device_id')`，UI 顯示 UUID；否則提示具體錯誤（缺權限/無網路/缺金鑰）
3. UI 調整：
   - 「裝置ID」移至「開發工具」，保留「重新讀取」按鈕；抓不到時顯示具體原因字串
   - 出車按鈕前置檢查：未取得 UUID 則攔截並顯示引導（開定位權限、連網、重試）
4. 後端持續日誌：
   - 保留 `trip_start` payload/resp 輸出；若仍 400，抓取 `validation_errors` 顯示到 App 提示框

## 進一步防呆（可選）
- 在插件 `startTracking` 捕捉例外並回傳 `{ ok:false, error }`，讓前端能呈現具體錯誤
- 在 App 啟動時若 key 缺失，直接顯示「金鑰未配置」提示，不進入出車流程

## 交付與驗證
- 更新 APK（1.1.91），包含：開發工具顯示ID、一次握手流程、出車前 UUID 檢查
- 驗證：
  1) 啟動 App → 開發工具 → 重新讀取 → 顯示 UUID
  2) 開始出車 → Cloud Run `trip_start 200` → 《系統》分頁寫入 `share_url`
  3) 結束出車 → 清空對應欄位

請確認以上方案，我將立即實作並重新打包 APK，並在插件與前端加入可觀測錯誤訊息，幫你定位到底是金鑰、權限或網路造成的未取得。