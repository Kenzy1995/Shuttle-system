"""
配置管理模組
統一管理所有配置常數和環境變數
"""
import os
from typing import List

# ========== Google Cloud 配置 ==========
GOOGLE_CLOUD_PROJECT = os.environ.get("GOOGLE_CLOUD_PROJECT", "shuttle-system-487204")
GCP_PROJECT_ID = os.environ.get("GCP_PROJECT_ID", GOOGLE_CLOUD_PROJECT)

# ========== Firebase 配置 ==========
FIREBASE_RTDB_URL = os.environ.get(
    "FIREBASE_RTDB_URL",
    f"https://{GOOGLE_CLOUD_PROJECT}-default-rtdb.asia-southeast1.firebasedatabase.app/"
)

# ========== Google Sheets 配置 ==========
SCOPES_READONLY = ["https://www.googleapis.com/auth/spreadsheets.readonly"]
SCOPES_FULL = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

SPREADSHEET_ID = "1o_kLeuwP5_G08YYLlZKIgcYzlU1NIZD5SQnHoO59YUw"

# 工作表名稱
SHEET_NAME_MAIN = "預約審核(櫃台)"  # 主資料表
SHEET_NAME_CAP = "可預約班次(web)"  # 剩餘可預約名額（權威來源）
SHEET_NAME_SYSTEM = "系統"  # 系統設定

# 表頭行索引（1-based）
HEADER_ROW_MAIN = 2
DEFAULT_SHEET = "可預約班次(web)"
DEFAULT_RANGE = "A1:Z"

# ========== 快取配置 ==========
CACHE_TTL_SECONDS = 5  # 快取 TTL（秒）

# ========== 併發鎖配置 ==========
LOCK_WAIT_SECONDS = 60  # 鎖等待時間（秒）
LOCK_STALE_SECONDS = 30  # 鎖過期時間（秒）
LOCK_POLL_INTERVAL = 2.0  # 鎖輪詢間隔（秒）

# ========== 預約狀態文字 ==========
BOOKED_TEXT = "✔️ 已預約 Booked"
CANCELLED_TEXT = "❌ 已取消 Cancelled"

# ========== 站點索引映射 ==========
PICK_INDEX_MAP_EXACT = {
    "福泰大飯店 Forte Hotel": 1,
    "南港展覽館捷運站 Nangang Exhibition Center - MRT Exit 3": 2,
    "南港火車站 Nangang Train Station": 3,
    "LaLaport Shopping Park": 4,
}

DROP_INDEX_MAP_EXACT = {
    "南港展覽館捷運站 Nangang Exhibition Center - MRT Exit 3": 2,
    "南港火車站 Nangang Train Station": 3,
    "LaLaport Shopping Park": 4,
    "福泰大飯店 Forte Hotel": 5,
}

# ========== 站點座標 ==========
STATION_COORDS = {
    "福泰大飯店 Forte Hotel": {"lat": 25.054964953523683, "lng": 121.63077275881052},
    "南港展覽館捷運站 Nangang Exhibition Center - MRT Exit 3": {
        "lat": 25.055017007293404,
        "lng": 121.61818547695053,
    },
    "南港火車站 Nangang Train Station": {
        "lat": 25.052822671279454,
        "lng": 121.60771823129633,
    },
    "LaLaport Shopping Park": {"lat": 25.05629820919232, "lng": 121.61700981622211},
    "福泰大飯店(回) Forte Hotel (Back)": {
        "lat": 25.054800375417987,
        "lng": 121.63117576557792,
    },
}

# ========== 主表允許欄位 ==========
MAIN_SHEET_HEADER_KEYS = {
    "申請日期",
    "最後操作時間",
    "預約編號",
    "往返",
    "日期",
    "班次",
    "車次",
    "上車地點",
    "下車地點",
    "姓名",
    "手機",
    "信箱",
    "預約人數",
    "櫃台審核",
    "預約狀態",
    "乘車狀態",
    "身分",
    "房號",
    "入住日期",
    "退房日期",
    "用餐日期",
    "上車索引",
    "下車索引",
    "涉及路段範圍",
    "QRCode編碼",
    "備註",
    "寄信狀態",
    "車次-日期時間",
    "主班次時間",
    "確認人數",
}

# ========== 可預約班次表必要欄位 ==========
CAP_REQ_HEADERS = ["去程 / 回程", "日期", "班次", "站點", "可預約人數"]

# ========== Email 配置 ==========
EMAIL_FROM_NAME = "汐止福泰大飯店"
EMAIL_FROM_ADDR = os.environ.get("SMTP_USER", "fortehotels.shuttle@gmail.com")
SMTP_HOST = os.environ.get("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.environ.get("SMTP_PORT", "587"))
SMTP_PASSWORD = os.environ.get("SMTP_PASSWORD", "")

# ========== CORS 配置 ==========
CORS_ORIGINS = [
    "https://shuttle-web-509045429779.asia-east1.run.app",
    "https://shuttle-web-ywrjpvbwya-de.a.run.app",
    "http://localhost:8080",
]

# ========== Base URL ==========
BASE_URL = os.environ.get(
    "BASE_URL", "https://shuttle-api-509045429779.asia-east1.run.app"
)

# ========== GPS 系統配置 ==========
GPS_TIMEOUT_SECONDS = 15 * 60  # GPS 超時時間（15分鐘）
AUTO_SHUTDOWN_MS = 40 * 60 * 1000  # 自動關閉時間（40分鐘，毫秒）

# ========== Port ==========
PORT = int(os.environ.get("PORT", 8080))

