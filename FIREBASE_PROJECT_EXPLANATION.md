# 🔍 Firebase 專案與 GCP 專案的關係說明

## ❓ 問題：為什麼有兩個專案？

您看到兩個專案：
1. **`shuttle-system-487204`** - 測試環境的 GCP 專案
2. **`shuttle-system-60d6a`** - Firebase 專案（可能自動創建了 GCP 專案）

---

## 🔍 Firebase 專案與 GCP 專案的關係

### 重要概念

**Firebase 專案實際上就是一個 GCP 專案**！

當您創建 Firebase 專案時：
- Firebase 會自動創建一個對應的 GCP 專案
- 或者，您可以將 Firebase 專案關聯到現有的 GCP 專案

### 當前情況分析

**`shuttle-system-60d6a`** 可能是：
1. **舊的正式環境專案**：原本的 Firebase 專案，對應一個 GCP 專案
2. **Firebase 自動創建的專案**：創建 Firebase 專案時自動創建的 GCP 專案

**`shuttle-system-487204`** 是：
- **新的測試環境專案**：您新創建的 GCP 專案

---

## ✅ 正確的配置方式

### 選項 1: 使用同一個專案（推薦）

**將 Firebase 專案遷移到測試環境的 GCP 專案**：

1. **在 Firebase Console 中**：
   - 前往：https://console.firebase.google.com/project/shuttle-system-60d6a/settings/general
   - 查看「專案編號」和「專案 ID」

2. **確認 Firebase 專案對應的 GCP 專案**：
   - 如果 `shuttle-system-60d6a` 是一個獨立的 GCP 專案，您需要：
     - 在測試環境的 GCP 專案 `shuttle-system-487204` 中創建新的 Firebase 專案
     - 或者將 Firebase 專案遷移到 `shuttle-system-487204`

### 選項 2: 保持兩個專案（如果必須）

如果必須使用兩個專案：
- **GCP 專案**：`shuttle-system-487204`（用於 Cloud Run、Artifact Registry 等）
- **Firebase 專案**：`shuttle-system-60d6a`（用於 Firebase Realtime Database）

**但需要確保**：
- 服務帳號 `shuttle-system@shuttle-system-487204.iam.gserviceaccount.com` 在 Firebase 專案 `shuttle-system-60d6a` 中有權限

---

## 🔧 建議的解決方案

### 方案 1: 在測試環境 GCP 專案中創建新的 Firebase 專案（推薦）

1. **在 Firebase Console 中創建新專案**：
   - 使用 GCP 專案 `shuttle-system-487204`
   - 創建新的 Firebase Realtime Database

2. **更新配置**：
   - 更新 `FIREBASE_RTDB_URL` 為新的 Firebase 專案 URL
   - 更新前端配置中的 Firebase URL

3. **優點**：
   - 所有資源在同一個 GCP 專案中
   - 權限管理更簡單
   - 符合 A/B 測試的隔離要求

### 方案 2: 在現有 Firebase 專案中添加服務帳號權限

如果繼續使用 `shuttle-system-60d6a`：
1. 在 Firebase 專案 `shuttle-system-60d6a` 中添加服務帳號 `shuttle-system@shuttle-system-487204.iam.gserviceaccount.com`
2. 授予 Firebase Admin SDK Administrator Service Agent 角色

---

## 📋 檢查步驟

### 1. 確認 Firebase 專案對應的 GCP 專案

前往 Firebase Console：
- https://console.firebase.google.com/project/shuttle-system-60d6a/settings/general

查看「專案編號」，然後在 GCP Console 中搜索這個專案編號，確認它對應哪個 GCP 專案。

### 2. 確認兩個專案的用途

- **`shuttle-system-487204`**：測試環境的 GCP 專案（Cloud Run、Artifact Registry）
- **`shuttle-system-60d6a`**：Firebase 專案（可能是舊的正式環境，或 Firebase 自動創建的）

### 3. 決定使用哪個方案

- **如果 `shuttle-system-60d6a` 是舊的正式環境**：建議在 `shuttle-system-487204` 中創建新的 Firebase 專案
- **如果必須共用 Firebase 專案**：確保服務帳號有權限

---

## 🔗 相關連結

- Firebase Console：https://console.firebase.google.com/project/shuttle-system-60d6a/settings/general
- GCP Console：https://console.cloud.google.com/home/dashboard
- Firebase 專案設置：https://console.firebase.google.com/project/shuttle-system-60d6a/settings/general

---

## ⚠️ 重要提示

**Firebase 專案就是 GCP 專案**！

當您創建 Firebase 專案時，它會自動創建一個對應的 GCP 專案。如果您看到兩個專案，可能是：
1. 舊的正式環境專案（`shuttle-system-60d6a`）
2. 新的測試環境專案（`shuttle-system-487204`）

為了 A/B 測試的隔離，建議在測試環境的 GCP 專案中創建新的 Firebase 專案。

