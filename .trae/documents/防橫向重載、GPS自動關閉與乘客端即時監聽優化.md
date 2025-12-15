## 方案總覽
- 乘客地圖採用 Firebase Web SDK 的 onValue 監聽（按需啟用）；預設不監聽，點「查看」才開始監聽並更新地圖。
- 後端移除乘客地圖分享連結生成與系統!D19 寫入，保持路線計算與 E19 啟用檢查。
- App 端加入 30 分鐘無位移≥500m 的自動關閉定位；修正螢幕旋轉不重載。
- 保持三後端分工，列出環境變數配置建議與 Firebase 安全規則。
- 版本升級並打包 APK。

## 乘客地圖（Firebase 監聽：按需啟用）
- 新增「查看即時位置」按鈕：
  - 未點擊前不載入 Firebase SDK，不監聽、不抓位置。
  - 點擊後：以 `fbkey`（Web API Key）+ `fbdb`（RTDB URL）初始化 SDK，對 `/driver_location` 啟動 onValue 監聽；位置改變即更新標記與高亮路徑。
  - 再次點擊或離開頁面：呼叫 off() 取消監聽，釋放資源。
- 路線資料：維持只在出車開始時由 `driver-api2` 寫入 `/trip/{trip_id}/route`（polyline+stops），乘客端載入一次渲染即可。
- 低頻備援：保留每 5 分鐘一次的輕量拉取模式作備援（無 SDK 或無監聽時啟用）。

## 後端調整（driver-api2）
- Trip Start：保留 E19 旗標檢查、日期/時間雙格式匹配；生成 Directions polyline 並寫入 Firebase。
- 移除：PASSENGER_MAP_URL_BASE / DRIVER_API_BASE 分享連結邏輯與系統!D19 寫入。
- 路線查詢端點：保留 `GET /api/driver/route?trip_id=...` 給乘客端（若乘客前端改為直接讀 Firebase，可逐步弱化此端點）。
- （可選）位置過期標記：若超過 N 分鐘未更新，回傳 `stale: true`，乘客端顯示「位置過期」。

## App 端優化
- 自動關閉定位：
  - 保留最近 30 分鐘座標（時間戳+lat/lng）；每次上傳前計算首尾距離（Haversine）。
  - 若距離 < 500m：停止上傳定時器、關閉定位開關並提示；司機可手動重新開啟。
  - 僅在「接駁司機」角色生效；櫃檯角色永遠關閉。
- 螢幕旋轉不重載：
  - 調整 AndroidManifest 主 Activity：加入 `android:configChanges="orientation|keyboardHidden|keyboard|screenSize|uiMode"`，避免橫向時重建。
  - 檢查前端是否有 resize 時強制 reload 的邏輯，改為僅重新排版。

## 環境變數與安全
- driver-api2：
  - `FIREBASE_RTDB_URL`（RTDB URL）
  - `GOOGLE_MAPS_API_KEY`（僅 Directions API，用伺服器端金鑰）
- 乘客 HTML：
  - 使用 Firebase Web SDK 的 `apiKey` + `databaseURL`；可透過查詢參數傳入或在頁面中配置。
- 其他後端：`booking-api` / `booking-manager` 保持現狀（只處理 Sheets）。
- Firebase 規則（依安全需求設定）：
  - 方案 A（公開讀）：允許唯讀讀取 `/driver_location` 與 `/trip/*/route`，利於乘客端直接讀取。
  - 方案 B（限制域名/Token）：搭配 App Check 或判斷 Referer 限制讀取來源，提升安全性。

## 版本升級與打包
- 版本號升級至 `1.1.102`（package.json、src/version.ts、android/app/build.gradle）。
- 打包：`npm run build` → `npx cap sync` → `./gradlew assembleRelease`。
- 輸出檔：`ForteDriver-1.1.102.apk`。

## 驗證
- 按「查看」才啟動 Firebase 監聽；取消監聽後停止更新。
- Trip Start 後 Firebase 出現 `route`；乘客地圖正確渲染導航路線。
- 30 分鐘無位移≥500m 自動關閉定位；螢幕橫向不重載。

若您同意，我將依此計劃開始修改程式並交付新版 APK。