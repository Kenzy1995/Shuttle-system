"""
shuttle_ops_api.py
FastAPI「寫入與營運」服務（/api/ops）
"""
from __future__ import annotations

import io
import os
import time
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

import qrcode
from fastapi import FastAPI, HTTPException, Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, validator

import gspread
from google.oauth2.service_account import Credentials


# ---------- 常數與工具 ----------

DEFAULT_SHEET_NAME = os.getenv("SHEET_NAME", "預約審核(櫃台)")

HEADER_ALIASES = {
    "申請日期": {"申請日期", "建立時間", "建立日期", "建立日期時間", "created_at", "Created At"},
    "最後操作時間": {"最後操作時間", "最後更新時間", "V欄位", "updated_at", "Updated At"},
    "預約編號": {"預約編號", "訂單編號", "booking_id", "Booking ID"},
    "往返": {"往返", "方向", "direction"},
    "日期": {"日期", "Date", "出發日期"},
    "班次": {"班次", "時間", "出發時間", "Schedule"},
    "車次": {"車次", "顯示車次", "顯示時間", "顯示日期時間"},
    "上車地點": {"上車地點", "上車站點", "上車", "Pickup Station", "Pickup"},
    "下車地點": {"下車地點", "下車站點", "下車", "Dropoff Station", "Dropoff"},
    "姓名": {"姓名", "name", "Name"},
    "手機": {"手機", "電話", "Phone"},
    "信箱": {"信箱", "Email", "email"},
    "預約人數": {"預約人數", "人數", "Passengers"},
    "櫃台審核": {"櫃台審核", "審核", "U欄位", "audit", "Audit"},
    "預約狀態": {"預約狀態", "狀態", "Status"},
    "乘車狀態": {"乘車狀態", "乘車", "已上車", "Board Status"},
    "身分": {"身分", "身分類型", "identity"},
    "房號": {"房號", "Room", "Room Number"},
    "入住日期": {"入住日期", "CheckIn", "Check-in Date"},
    "退房日期": {"退房日期", "CheckOut", "Check-out Date"},
    "用餐日期": {"用餐日期", "Dining Date"},
    "上車索引": {"上車索引", "PickupIndex"},
    "下車索引": {"下車索引", "DropIndex"},
    "涉及路段範圍": {"涉及路段範圍", "Segments"},
    "QRCode編碼": {"QRCode編碼", "QR內容", "QR Code", "QRCode", "QR碼編碼", "QR"},
}

STOP_ALIASES = {
    "福泰大飯店": {"福泰大飯店", "Forte Hotel", "Forte Hotel Xizhi", "福泰大飯店 Forte Hotel"},
    "南港展覽館-捷運3號出口": {
        "南港展覽館-捷運3號出口",
        "南港展覽館捷運站",
        "Nangang Exhibition Center - MRT Exit 3",
        "南港展覽館捷運站 Nangang Exhibition Center - MRT Exit 3",
        "南港展覽館捷運站 Exit 3",
    },
    "南港火車站": {"南港火車站", "Nangang Train Station", "南港火車站 Nangang Train Station"},
    "南港 LaLaport Shopping Park": {"南港 LaLaport Shopping Park", "LaLaport", "南港 LaLaport"},
}

ROUTE_ORDER = [
    "福泰大飯店",
    "南港展覽館-捷運3號出口",
    "南港火車站",
    "南港 LaLaport Shopping Park",
    "福泰大飯店",
]


def _normalize_stop(name: str) -> str:
    raw = (name or "").strip()
    for key, aliases in STOP_ALIASES.items():
        if raw in aliases:
            return key
        for a in aliases:
            if raw.lower() == a.lower():
                return key
    return raw


def _tz_now_str() -> str:
    try:
        os.environ.setdefault("TZ", "Asia/Taipei")
        time.tzset()  # type: ignore[attr-defined]
    except Exception:
        pass
    t = time.localtime()
    return f"{t.tm_year}/{t.tm_mon}/{t.tm_mday} {t.tm_hour:02d}:{t.tm_min:02d}"


def _display_trip_str(date_iso: str, time_hm: str) -> str:
    y, m, d = date_iso.split("-")
    m = str(int(m))
    d = str(int(d))
    return f"'%s/%s %s" % (m, d, time_hm)


def _time_hm_from_any(s: str) -> str:
    s = (s or "").strip().replace("：", ":")
    if " " in s and ":" in s:
        hm = s.split()[-1]
        return hm[:5]
    if ":" in s:
        return s[:5]
    return s


def _compute_indices_and_segments(direction: str, pickup: str, dropoff: str):
    norm_pick = _normalize_stop(pickup)
    norm_drop = _normalize_stop(dropoff)

    def base_index(stop: str) -> int:
        for i, s in enumerate(ROUTE_ORDER, start=1):
            if stop == s:
                return i
        return 0

    pick_idx = base_index(norm_pick)
    drop_idx = base_index(norm_drop)

    if norm_pick == "福泰大飯店" and direction == "去程":
        pick_idx = 1
    if norm_drop == "福泰大飯店" and direction == "回程":
        drop_idx = 5

    lo = min(pick_idx, drop_idx)
    hi = max(pick_idx, drop_idx)
    segments = [str(i) for i in range(lo, max(lo, hi))]
    if segments and segments[-1] == str(hi):
        segments = segments[:-1]
    seg_str = ",".join(segments)
    return pick_idx, drop_idx, seg_str


def _mmdd_prefix(date_iso: str) -> str:
    y, m, d = date_iso.split("-")
    return f"{int(m):02d}{int(d):02d}"


# ---------- Google Sheets ----------

def open_sheet() -> gspread.Worksheet:
    json_path = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON")
    if not json_path or not os.path.exists(json_path):
        raise RuntimeError("找不到 GOOGLE_SERVICE_ACCOUNT_JSON 指定的憑證檔")

    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]
    credentials = Credentials.from_service_account_file(json_path, scopes=scopes)
    gc = gspread.authorize(credentials)

    spreadsheet_id = os.getenv("SPREADSHEET_ID")
    if not spreadsheet_id:
        raise RuntimeError("請設定環境變數 SPREADSHEET_ID")

    sh = gc.open_by_key(spreadsheet_id)
    ws = sh.worksheet(os.getenv("SHEET_NAME", DEFAULT_SHEET_NAME))
    return ws


def header_map(ws: gspread.Worksheet) -> Dict[str, int]:
    row = ws.row_values(1)
    m: Dict[str, int] = {}
    for idx, name in enumerate(row, start=1):
        name = (name or "").strip()
        if not name:
            continue
        for std, aliases in HEADER_ALIASES.items():
            if name == std or name in aliases:
                if std not in m:
                    m[std] = idx
    return m


def _read_all_rows(ws: gspread.Worksheet) -> List[List[str]]:
    return ws.get_all_values()


def _find_rows_by_pred(ws: gspread.Worksheet, pred) -> List[int]:
    values = _read_all_rows(ws)
    if not values:
        return []
    headers = values[0]
    result_rows: List[int] = []
    for i in range(1, len(values)):
        row = values[i]
        row_dict = {headers[j]: row[j] if j < len(row) else "" for j in range(len(headers))}
        if pred(row_dict):
            result_rows.append(i + 1)
    return result_rows


def _get_max_seq_for_date(ws: gspread.Worksheet, date_iso: str) -> int:
    m = header_map(ws)
    all_values = _read_all_rows(ws)
    if not all_values:
        return 0
    try:
        c_id = m["預約編號"]
    except KeyError:
        return 0
    prefix = _mmdd_prefix(date_iso)
    max_seq = 0
    for i in range(1, len(all_values)):
        row = all_values[i]
        booking = row[c_id - 1] if c_id - 1 < len(row) else ""
        if booking.startswith(prefix):
            tail = booking[len(prefix):]
            try:
                seq = int(tail)
                max_seq = max(max_seq, seq)
            except ValueError:
                continue
    return max_seq


# ---------- FastAPI ----------
app = FastAPI(title="Shuttle Ops API", version="1.0.1")

# ====== 改良版 CORS ======
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://hotel-web-995728097341.asia-east1.run.app"
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health():
    return {"status": "ok", "time": _tz_now_str()}


@app.get("/api/qr/{code}")
def qr_image(code: str):
    img = qrcode.make(code)
    bio = io.BytesIO()
    img.save(bio, format="PNG")
    return Response(content=bio.getvalue(), media_type="image/png")


# ====== 其餘 /api/ops 功能保持不變 ======
# （照你原本版本無需更動）
# ...
