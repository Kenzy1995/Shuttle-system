## 金鑰與安全
- 使用兩個金鑰：
  - `VITE_GOOGLE_MAPS_API_KEY`：前端地圖渲染（已在乘客 HTML 使用）。
  - `GOOGLE_MAPS_API_KEY`：後端專用，用於呼叫 Google Directions API 生成導航路線。
- 設定方式：在 Cloud Run 服務 `driver-api2` 的環境變數加入 `GOOGLE_MAPS_API_KEY`（可先用您現有的金鑰；建議另建一把只允許「Directions API」的後端金鑰）。

## 後端：生成真實導航路線
- 在 `server.py` 出車開始端點中，於現有「讀《車次管理(櫃台)》H:K 停靠站」之後：
  - 以第一站為 `origin`、最後一站為 `destination`，中間停靠站作為 `waypoints`，順序不變。
  - 呼叫 `https://maps.googleapis.com/maps/api/directions/json`（mode=driving）取得 `overview_polyline.points`。
  - 解碼 polyline 成座標序列，與 `stops` 一起寫入 Firebase `/trip/{trip_id}/route`：
    - `{ stops: [...], polyline: { points: "...", path: [[lat,lng], ...] } }`
  - 若 Directions 失敗，退化為「直線連接停靠站」。
- 日期/時間匹配：維持雙格式匹配（`YYYY/MM/DD`/`YYYY-MM-DD`、時間 `HH:MM` 容忍不補零）以定位《車次管理》目標列。（現已在 `server.py:1241` 附近處理，將補上路線生成）

## 乘客 HTML：渲染導航路線
- 在 `driver-app/public/realtime-map.html`：
  - 新增：讀取 `/trip/{trip_id}/route`（或直接讀 Firebase 同路徑）取得 `stops` 與 `polyline`。
  - 使用 Google Maps JS API：
    - 畫出主路線 polyline（粗藍線）。
    - 站點以具辨識度的標記（含「福泰(回)」）；車標記平滑移動。
    - 高亮進度：根據司機位置在 polyline 上找最近點，將已行走段加深色或加粗，未行走段淡化。
  - 刷新策略保持：預設 5 分鐘自動刷新＋右上角「手動刷新」。

## 版本升級與打包 APK
- 版本號：升至 `1.1.101`（`package.json`、`src/version.ts`、`android/app/build.gradle` 的 `versionCode`/`versionName`）。
- 打包流程：
  - `npm run build`
  - `npx cap sync`
  - `android/gradlew assembleRelease`
- 命名規則維持：`ForteDriver-1.1.101.apk` 產出於 `android/app/build/outputs/apk/release/`。

## 驗證
- 出車開始後：Firebase `/trip/{trip_id}/route` 出現 `stops`＋`polyline`；乘客地圖正確顯示道路導航路線。
- 位置更新：已行走段高亮、狀態顯示最近更新時間；手動刷新可即時更新。

若您同意，我將立即：
1) 為後端加入 Directions API 呼叫與 polyline 寫入；2) 調整乘客地圖以渲染路線；3) 更新版本號並打包新版 APK。