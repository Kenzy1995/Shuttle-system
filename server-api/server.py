# Unified Shuttle System Backend API
# Rebuild trigger: 2026-02-12
from __future__ import annotations
import io
import os
import re
import time
import math
import json
import base64
import logging
import threading
from threading import Lock
import secrets
import hashlib
import smtplib
import urllib.parse
import urllib.request
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders

import qrcode
import firebase_admin
from firebase_admin import credentials, db
from fastapi import FastAPI, HTTPException, Response, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, validator
import gspread
import google.auth
from google.auth import default
from googleapiclient.discovery import build

# ========== 日誌設定 ==========
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("shuttle-api")

# ========== 配置常數 ==========
EMAIL_FROM_NAME = "汐止福泰大飯店"
EMAIL_FROM_ADDR = "fortehotels.shuttle@gmail.com"

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

SPREADSHEET_ID = "1o_kLeuwP5_G08YYLlZKIgcYzlU1NIZD5SQnHoO59YUw"
SHEET_NAME_MAIN = "預約審核(櫃台)"
SHEET_NAME_CAP = "可預約班次(web)"
SHEET_NAME_SYSTEM = "系統"
DEFAULT_SHEET = "可預約班次(web)"
DEFAULT_RANGE = "A1:Z"
HEADER_ROW_MAIN = 2

# Base URL for generating QR code images and API endpoints
BASE_URL = os.environ.get("BASE_URL", "https://server-api-509045429779.asia-east1.run.app")

BOOKED_TEXT = "✔️ 已預約 Booked"
CANCELLED_TEXT = "❌ 已取消 Cancelled"

CACHE_TTL_SECONDS = 5
LOCK_WAIT_SECONDS = 60
LOCK_STALE_SECONDS = 30
LOCK_POLL_INTERVAL = 2.0
GPS_TIMEOUT_SECONDS = 15 * 60
AUTO_SHUTDOWN_MS = 40 * 60 * 1000

HEADER_KEYS = {
    "申請日期", "最後操作時間", "預約編號", "往返", "日期", "班次", "車次",
    "上車地點", "下車地點", "姓名", "手機", "信箱", "預約人數", "櫃台審核",
    "預約狀態", "乘車狀態", "身分", "房號", "入住日期", "退房日期", "用餐日期",
    "上車索引", "下車索引", "涉及路段範圍", "QRCode編碼", "備註", "寄信狀態",
    "車次-日期時間", "主班次時間", "確認人數", "確認狀態"
}

CAP_REQ_HEADERS = ["去程 / 回程", "日期", "班次", "站點", "可預約人數"]

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

STATION_COORDS = {
    "福泰大飯店 Forte Hotel": {"lat": 25.054964953523683, "lng": 121.63077275881052},
    "南港展覽館捷運站 Nangang Exhibition Center - MRT Exit 3": {"lat": 25.055017007293404, "lng": 121.61818547695053},
    "南港火車站 Nangang Train Station": {"lat": 25.052822671279454, "lng": 121.60771823129633},
    "LaLaport Shopping Park": {"lat": 25.05629820919232, "lng": 121.61700981622211},
    "福泰大飯店(回) Forte Hotel (Back)": {"lat": 25.054800375417987, "lng": 121.63117576557792},
}

# ========== 快取和鎖 ==========
SHEET_CACHE: Dict[str, Any] = {
    "values": None,
    "header_map": None,
    "fetched_at": None,
    "sheet_name": None,
    "range_name": None,
}
CACHE_LOCK = threading.Lock()

# ========== 核銷快取隊列（用於批量寫回 Sheet）==========
# 結構：{booking_id: {sub_index: {"status": "checked_in", "checked_at": str, "checked_by": str}}}
CHECKIN_CACHE: Dict[str, Dict[int, Dict[str, Any]]] = {}
CHECKIN_CACHE_LOCK = threading.Lock()
CHECKIN_FLUSH_INTERVAL = 3.0  # 3 秒後批量寫回
_last_flush_time = 0.0

CAP_SHEET_CACHE: Dict[str, Any] = {
    "values": None,
    "header_map": None,
    "hdr_row": None,
    "fetched_at": None,
}

DRIVER_LOCATION_CACHE: Dict[str, Any] = {
    "lat": 0.0,
    "lng": 0.0,
    "timestamp": 0.0,
    "updated_at": None
}
LOCATION_LOCK = Lock()

_gc_cache: Optional[gspread.Client] = None
_gc_lock = Lock()
_ws_cache: Dict[str, gspread.Worksheet] = {}
_ws_lock = Lock()

# ========== 工具函數 ==========
def _email_hash6(email: str) -> str:
    return hashlib.sha256((email or "").encode("utf-8")).hexdigest()[:6]

def _generate_ticket_hash(booking_id: str, sub_index: int, email: str) -> str:
    """生成子票 hash（用於 QR Code 驗證）"""
    raw = f"{booking_id}:{sub_index}:{email}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:6]

def _tz_now() -> datetime:
    os.environ.setdefault("TZ", "Asia/Taipei")
    try:
        time.tzset()
    except Exception:
        pass
    return datetime.now()

def _tz_now_str() -> str:
    t = _tz_now()
    return t.strftime("%Y-%m-%d %H:%M:%S")

def _today_iso_taipei() -> str:
    t = _tz_now()
    return t.strftime("%Y-%m-%d")

def _time_hm_from_any(s: str) -> str:
    s = (s or "").strip().replace("：", ":")
    if " " in s and ":" in s:
        return s.split()[-1][:5]
    if ":" in s:
        return s[:5]
    return s

def _display_trip_str(date_iso: str, time_hm: str) -> str:
    if not date_iso or not time_hm:
        return ""
    y, m, d = date_iso.split("-")
    return f"{int(m)}/{int(d)} {time_hm}"

def _compute_indices_and_segments(pickup: str, dropoff: str):
    ps = (pickup or "").strip()
    ds = (dropoff or "").strip()
    pick_idx = PICK_INDEX_MAP_EXACT.get(ps, 0)
    drop_idx = DROP_INDEX_MAP_EXACT.get(ds, 0)
    if pick_idx == 0 or drop_idx == 0 or drop_idx <= pick_idx:
        return pick_idx, drop_idx, ""
    segs = list(range(pick_idx, drop_idx))
    seg_str = ",".join(str(i) for i in segs)
    return pick_idx, drop_idx, seg_str

def _compute_main_departure_datetime(direction: str, pickup: str, date_iso: str, time_hm: str) -> str:
    date_iso = (date_iso or "").strip()
    time_hm = _time_hm_from_any(time_hm or "")
    if not date_iso or not time_hm:
        return ""
    try:
        dt = datetime.strptime(f"{date_iso} {time_hm}", "%Y-%m-%d %H:%M")
    except Exception:
        return ""
    if direction != "回程":
        return dt.strftime("%Y/%m/%d %H:%M")
    p = (pickup or "").strip()
    offset_min = 0
    if "捷運" in p or "Exhibition Center" in p:
        offset_min = 5
    elif "火車" in p or "Train Station" in p:
        offset_min = 10
    elif "LaLaport" in p:
        offset_min = 20
    if offset_min:
        dt = dt - timedelta(minutes=offset_min)
    return dt.strftime("%Y/%m/%d %H:%M")

def _normalize_station_for_capacity(direction: str, pick: str, drop: str) -> str:
    return (drop if direction == "去程" else pick).strip()

def _normalize_text(s: str) -> str:
    return " ".join((s or "").replace("　", " ").split())

def _parse_available(s: str) -> Optional[int]:
    if s is None:
        return None
    m = re.search(r"(\d+)", str(s))
    return int(m.group(1)) if m else None

def _safe_int(v: Any, default: int = 0) -> int:
    try:
        s = str(v).strip()
        if not s:
            return default
        return int(float(s))
    except Exception:
        return default

def _normalize_main_dt_format(main_raw: str) -> str:
    if not main_raw:
        return main_raw
    pattern = r'^(\d{4})[/-](\d{1,2})[/-](\d{1,2})\s+(\d{1,2}):(\d{2})(?::(\d{2}))?$'
    match = re.match(pattern, main_raw.strip())
    if match:
        year, month, day, hour, minute, second = match.groups()
        normalized_hour = hour.zfill(2)
        normalized_month = month.zfill(2)
        normalized_day = day.zfill(2)
        if second:
            return f"{year}/{normalized_month}/{normalized_day} {normalized_hour}:{minute}:{second}"
        else:
            return f"{year}/{normalized_month}/{normalized_day} {normalized_hour}:{minute}"
    return main_raw

def _parse_main_dt(raw: str) -> Optional[datetime]:
    if not raw:
        return None
    original_raw = raw
    raw = raw.strip()
    pattern = r'^(\d{4})[/-](\d{1,2})[/-](\d{1,2})\s+(\d{1,2}):(\d{2})(?::(\d{2}))?$'
    match = re.match(pattern, raw)
    if match:
        year = match.group(1)
        month = match.group(2).zfill(2)
        day = match.group(3).zfill(2)
        hour = match.group(4).zfill(2)
        minute = match.group(5)
        second = match.group(6) if match.lastindex >= 6 and match.group(6) else None
        date_part = f"{year}/{month}/{day}"
        if second:
            raw = f"{date_part} {hour}:{minute}:{second}"
        else:
            raw = f"{date_part} {hour}:{minute}"
    for fmt in ("%Y/%m/%d %H:%M", "%Y-%m-%d %H:%M", "%Y/%m/%d %H:%M:%S", "%Y-%m-%d %H:%M:%S"):
        try:
            result = datetime.strptime(raw, fmt)
            return result
        except ValueError:
            continue
    for fmt in ("%Y/%m/%d", "%Y-%m-%d"):
        try:
            return datetime.strptime(raw, fmt)
        except ValueError:
            continue
    log.warning(f"無法解析主班次時間格式: {original_raw}")
    return None

def haversine_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    R = 6371000
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)
    a = math.sin(delta_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2) ** 2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c

def get_next_station(stops: list, completed_stops: list) -> str:
    for stop in stops:
        stop_name = stop if isinstance(stop, str) else stop.get("name", "")
        if stop_name and stop_name not in completed_stops:
            return stop_name
    return ""

# ========== Google Sheets 操作 ==========
def _get_gspread_client() -> gspread.Client:
    global _gc_cache
    if _gc_cache is None:
        with _gc_lock:
            if _gc_cache is None:
                creds, _ = google.auth.default(scopes=SCOPES)
                _gc_cache = gspread.authorize(creds)
    return _gc_cache

def _invalidate_ws_cache(sheet_name: Optional[str] = None) -> None:
    with _ws_lock:
        if sheet_name is None:
            _ws_cache.clear()
        else:
            _ws_cache.pop(sheet_name, None)

def open_ws(name: str) -> gspread.Worksheet:
    with _ws_lock:
        if name in _ws_cache:
            return _ws_cache[name]
    gc = _get_gspread_client()
    sh = gc.open_by_key(SPREADSHEET_ID)
    ws = sh.worksheet(name)
    with _ws_lock:
        _ws_cache[name] = ws
    return ws

def _sheet_headers(ws: gspread.Worksheet, header_row: int, values: Optional[List[List[str]]] = None) -> List[str]:
    if values is not None and len(values) >= header_row:
        headers = values[header_row - 1]
    else:
        headers = ws.row_values(header_row)
    return [(h or "").strip() for h in headers]

def header_map_main(ws: Optional[gspread.Worksheet] = None, values: Optional[List[List[str]]] = None) -> Dict[str, int]:
    if values is not None:
        if len(values) < HEADER_ROW_MAIN:
            return {}
        row = values[HEADER_ROW_MAIN - 1]
        m: Dict[str, int] = {}
        for idx, name in enumerate(row, start=1):
            name = (name or "").strip()
            if name in HEADER_KEYS and name not in m:
                m[name] = idx
        return m
    else:
        if ws is None:
            raise ValueError("必須提供 ws 或 values")
        row = _sheet_headers(ws, HEADER_ROW_MAIN)
        m: Dict[str, int] = {}
        for idx, name in enumerate(row, start=1):
            name = (name or "").strip()
            if name in HEADER_KEYS and name not in m:
                m[name] = idx
        return m

def _read_all_rows(ws: gspread.Worksheet) -> List[List[str]]:
    return ws.get_all_values()

def _col_index(hmap: Dict[str, int], name: str) -> int:
    col = hmap.get(name)
    return col - 1 if col else -1

def _get_cell(row: List[str], idx: int) -> str:
    if idx < 0 or idx >= len(row):
        return ""
    return (row[idx] or "").strip()

def _find_rows_by_pred(ws: gspread.Worksheet, headers: List[str], start_row: int, pred) -> List[int]:
    values = _read_all_rows(ws)
    if not values:
        return []
    hdrs = values[start_row - 1] if len(values) >= start_row else []
    result: List[int] = []
    for i, row in enumerate(values[start_row:], start=start_row + 1):
        if not any(row):
            continue
        d = {hdrs[j]: row[j] if j < len(row) else "" for j in range(len(hdrs))}
        if pred(d):
            result.append(i)
    return result

def _find_qrcode_row(values: List[List[str]], hmap: Dict[str, int], qrcode_value: str) -> Optional[int]:
    col = hmap.get("QRCode編碼")
    if not col:
        return None
    ci = col - 1
    for i, row in enumerate(values[HEADER_ROW_MAIN:], start=HEADER_ROW_MAIN + 1):
        if ci < len(row) and (row[ci] or "").strip() == qrcode_value:
            return i
    return None

def _find_qrcode_row_json(values: List[List[str]], hmap: Dict[str, int], booking_id: str, sub_index: int) -> Optional[int]:
    """在 Sheet 的 QRCode編碼（JSON）中查找子票對應的預約行"""
    col = hmap.get("QRCode編碼")
    if not col:
        return None
    
    ci = col - 1
    import json
    
    for i, row in enumerate(values[HEADER_ROW_MAIN:], start=HEADER_ROW_MAIN + 1):
        if ci < len(row):
            qr_cell = (row[ci] or "").strip()
            if not qr_cell:
                continue
            
            # 嘗試解析 JSON
            try:
                qr_dict = json.loads(qr_cell)
                if isinstance(qr_dict, dict):
                    # 檢查是否包含該子票的 QR Code
                    sub_key = str(sub_index)
                    if sub_key in qr_dict:
                        # 驗證 booking_id 是否匹配
                        qr_content = qr_dict[sub_key]
                        if isinstance(qr_content, dict):
                            # 新格式：{"qr": "FT:...", "status": "...", "pax": 2}
                            qr_str = qr_content.get("qr", "")
                        else:
                            # 舊格式：直接是 QR Code 字符串
                            qr_str = str(qr_content)
                        
                        if qr_str.startswith(f"FT:{booking_id}:{sub_index}:"):
                            # 驗證預約編號
                            idx_booking = _col_index(hmap, "預約編號")
                            if idx_booking >= 0 and idx_booking < len(row):
                                if (row[idx_booking] or "").strip() == booking_id:
                                    return i
            except (json.JSONDecodeError, ValueError, AttributeError):
                # 如果不是 JSON，跳過（可能是舊格式）
                continue
    
    return None

def _find_booking_row(values: List[List[str]], hmap: Dict[str, int], booking_id: str) -> Optional[int]:
    idx_booking = _col_index(hmap, "預約編號")
    if idx_booking < 0:
        return None
    for i, row in enumerate(values[HEADER_ROW_MAIN:], start=HEADER_ROW_MAIN + 1):
        if idx_booking < len(row) and (row[idx_booking] or "").strip() == booking_id:
            return i
    return None

def _col_letter(col_idx: int) -> str:
    return gspread.utils.rowcol_to_a1(1, col_idx).replace("1", "")

# ========== 快取管理 ==========
def _get_cached_sheet_data(sheet_name: str, range_name: str):
    now = datetime.now()
    global SHEET_CACHE
    with CACHE_LOCK:
        cached_values = SHEET_CACHE.get("values")
        cached_sheet = SHEET_CACHE.get("sheet_name")
        cached_range = SHEET_CACHE.get("range_name")
        fetched_at = SHEET_CACHE.get("fetched_at")
        if (
            cached_values is not None
            and cached_sheet == sheet_name
            and cached_range == range_name
            and fetched_at is not None
            and (now - fetched_at).total_seconds() < CACHE_TTL_SECONDS
        ):
            return cached_values
    return None

def _set_cached_sheet_data(sheet_name: str, range_name: str, values: list):
    global SHEET_CACHE
    with CACHE_LOCK:
        SHEET_CACHE = {
            "values": values,
            "fetched_at": datetime.now(),
            "sheet_name": sheet_name,
            "range_name": range_name
        }

def _get_sheet_data_main() -> Tuple[List[List[str]], Dict[str, int]]:
    now = _tz_now()
    global SHEET_CACHE
    with CACHE_LOCK:
        cached_values = SHEET_CACHE.get("values")
        fetched_at: Optional[datetime] = SHEET_CACHE.get("fetched_at")
        if (
            cached_values is not None
            and fetched_at is not None
            and (now - fetched_at).total_seconds() < CACHE_TTL_SECONDS
        ):
            return cached_values, SHEET_CACHE["header_map"]
    ws = open_ws(SHEET_NAME_MAIN)
    values = _read_all_rows(ws)
    hmap = header_map_main(ws, values)
    SHEET_CACHE = {
        "values": values,
        "header_map": hmap,
        "fetched_at": now,
    }
    return values, hmap

def _invalidate_sheet_cache() -> None:
    global SHEET_CACHE
    with CACHE_LOCK:
        SHEET_CACHE = {
            "values": None,
            "header_map": None,
            "fetched_at": None,
        }
    _invalidate_ws_cache(SHEET_NAME_MAIN)

def _invalidate_cap_sheet_cache() -> None:
    global CAP_SHEET_CACHE
    with CACHE_LOCK:
        CAP_SHEET_CACHE = {
            "values": None,
            "header_map": None,
            "hdr_row": None,
            "fetched_at": None,
        }

def _find_cap_header_row(values: List[List[str]]) -> int:
    for i in range(min(5, len(values))):
        row = [c.strip() for c in values[i]]
        if "去程 / 回程" in row and "可預約人數" in row:
            return i + 1
    return 1

def _cap_header_map(values: List[List[str]]) -> Tuple[Dict[str, int], int]:
    hdr_row = _find_cap_header_row(values)
    headers = [c.strip() for c in (values[hdr_row-1] if len(values) >= hdr_row else [])]
    m: Dict[str, int] = {}
    for idx, name in enumerate(headers, start=1):
        if name in CAP_REQ_HEADERS and name not in m:
            m[name] = idx
    return m, hdr_row

def _get_cap_sheet_data() -> Tuple[List[List[str]], Dict[str, int], int]:
    now = _tz_now()
    global CAP_SHEET_CACHE
    with CACHE_LOCK:
        cached_values = CAP_SHEET_CACHE.get("values")
        cached_hmap = CAP_SHEET_CACHE.get("header_map")
        cached_hdr_row = CAP_SHEET_CACHE.get("hdr_row")
        fetched_at: Optional[datetime] = CAP_SHEET_CACHE.get("fetched_at")
        if (
            cached_values is not None
            and cached_hmap is not None
            and cached_hdr_row is not None
            and fetched_at is not None
            and (now - fetched_at).total_seconds() < CACHE_TTL_SECONDS
        ):
            return cached_values, cached_hmap, cached_hdr_row
    ws_cap = open_ws(SHEET_NAME_CAP)
    try:
        head_chunk = ws_cap.get("A1:AZ10")
        hdr_row = _find_cap_header_row(head_chunk)
        headers = [c.strip() for c in (head_chunk[hdr_row - 1] if len(head_chunk) >= hdr_row else [])]
        m_full: Dict[str, int] = {}
        for idx, name in enumerate(headers, start=1):
            if name in CAP_REQ_HEADERS and name not in m_full:
                m_full[name] = idx
        if any(key not in m_full for key in CAP_REQ_HEADERS):
            raise ValueError("cap headers not found in head chunk")
        min_idx = min(m_full[k] for k in CAP_REQ_HEADERS)
        max_idx = max(m_full[k] for k in CAP_REQ_HEADERS)
        start_col = _col_letter(min_idx)
        end_col = _col_letter(max_idx)
        values = ws_cap.get(f"{start_col}{hdr_row}:{end_col}{ws_cap.row_count}")
        shift = min_idx - 1
        m = {k: (m_full[k] - shift) for k in CAP_REQ_HEADERS}
        hdr_row_local = 1
    except Exception:
        values = _read_all_rows(ws_cap)
        m, hdr_row = _cap_header_map(values)
        hdr_row_local = hdr_row
    CAP_SHEET_CACHE = {
        "values": values,
        "header_map": m,
        "hdr_row": hdr_row_local,
        "fetched_at": now,
    }
    return values, m, hdr_row_local

def lookup_capacity(direction: str, date_iso: str, time_hm: str, station: str) -> int:
    values, m, hdr_row = _get_cap_sheet_data()
    for key in CAP_REQ_HEADERS:
        if key not in m:
            raise HTTPException(409, f"capacity_header_missing:{key}")
    idx_dir = m["去程 / 回程"] - 1
    idx_date = m["日期"] - 1
    idx_time = m["班次"] - 1
    idx_st = m["站點"] - 1
    idx_avail = m["可預約人數"] - 1
    want_dir = _normalize_text(direction)
    want_date = date_iso.strip()
    want_time = _time_hm_from_any(time_hm)
    want_station = _normalize_text(station)
    for row in values[hdr_row:]:
        if not any(row):
            continue
        r_dir = _normalize_text(row[idx_dir] if idx_dir < len(row) else "")
        r_date = (row[idx_date] if idx_date < len(row) else "").strip()
        r_time = _time_hm_from_any(row[idx_time] if idx_time < len(row) else "")
        r_st = _normalize_text(row[idx_st] if idx_st < len(row) else "")
        r_avail = row[idx_avail] if idx_avail < len(row) else ""
        if r_dir == want_dir and r_date == want_date and r_time == want_time and r_st == want_station:
            avail = _parse_available(r_avail)
            if avail is None:
                raise HTTPException(409, "capacity_not_numeric")
            return avail
    raise HTTPException(409, "capacity_not_found")

# ========== Firebase 操作 ==========
def _init_firebase():
    try:
        if not firebase_admin._apps:
            service_account_path = "service_account.json"
            if os.path.exists(service_account_path):
                cred = credentials.Certificate(service_account_path)
                log.info("Firebase: Using service account file")
            else:
                cred = credentials.ApplicationDefault()
                log.info("Firebase: Using ApplicationDefault credentials")
            db_url = os.environ.get("FIREBASE_RTDB_URL")
            if not db_url:
                project_id = os.environ.get("GOOGLE_CLOUD_PROJECT", "shuttle-system-487204")
                db_url = f"https://{project_id}-default-rtdb.asia-southeast1.firebasedatabase.app/"
                log.warning(f"Firebase: FIREBASE_RTDB_URL not set, using default: {db_url}")
            else:
                log.info(f"Firebase: Using FIREBASE_RTDB_URL from env: {db_url}")
            firebase_admin.initialize_app(cred, {"databaseURL": db_url})
            log.info("Firebase: Initialization successful")
            _ensure_firebase_paths()
        return True
    except Exception as e:
        log.error(f"Firebase initialization failed: {type(e).__name__}: {str(e)}")
        return False

def _ensure_firebase_paths():
    try:
        paths = ["/sheet_locks", "/booking_seq", "/tickets"]
        for path in paths:
            ref = db.reference(path)
            snapshot = ref.get()
            if snapshot is None:
                ref.set({})
                log.info(f"Firebase: Initialized path {path}")
    except Exception as e:
        log.warning(f"Firebase: Failed to ensure paths: {type(e).__name__}: {str(e)}")

# ========== 併發鎖管理 ==========
def _lock_id_for_capacity(date_iso: str, time_hm: str) -> str:
    raw = f"{date_iso}|{_time_hm_from_any(time_hm)}"
    h = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]
    return f"cap_{h}"

def _acquire_capacity_lock(lock_id: str, date_iso: str, time_hm: str, timeout_s: int = LOCK_WAIT_SECONDS):
    if not _init_firebase():
        return None
    ref = db.reference(f"/sheet_locks/{lock_id}")
    holder = secrets.token_hex(8)
    start = time.monotonic()
    stale_ms = LOCK_STALE_SECONDS * 1000
    lock_date = (date_iso or "").strip()
    lock_time = _time_hm_from_any(time_hm)
    log.info(f"[cap_lock] wait_start lock_id={lock_id} date={lock_date} time={lock_time}")
    poll_no = 0
    while (time.monotonic() - start) < timeout_s:
        now_ms = int(time.time() * 1000)
        poll_no += 1
        def txn(current):
            if current is None:
                return {"holder": holder, "ts": now_ms, "date": lock_date, "time": lock_time}
            if isinstance(current, dict) and current.get("released") is True:
                return {"holder": holder, "ts": now_ms, "date": lock_date, "time": lock_time}
            cur_ts = int(current.get("ts", 0)) if isinstance(current, dict) else 0
            if cur_ts and (now_ms - cur_ts) > stale_ms:
                return {"holder": holder, "ts": now_ms, "date": lock_date, "time": lock_time}
            return current
        try:
            result = ref.transaction(txn)
            if isinstance(result, dict) and result.get("holder") == holder:
                waited_ms = int((time.monotonic() - start) * 1000)
                log.info(f"[cap_lock] acquired lock_id={lock_id} holder={holder} waited_ms={waited_ms} date={lock_date} time={lock_time}")
                return holder
            if isinstance(result, dict):
                seen_holder = result.get("holder")
                seen_ts = result.get("ts")
                seen_date = result.get("date")
                seen_time = result.get("time")
                log.info(f"[cap_lock] poll={poll_no} lock_id={lock_id} seen_holder={seen_holder} seen_ts={seen_ts} seen_date={seen_date} seen_time={seen_time} now_ms={now_ms} stale_ms={stale_ms}")
            else:
                log.info(f"[cap_lock] poll={poll_no} lock_id={lock_id} seen_non_dict={result} now_ms={now_ms}")
        except Exception as e:
            log.warning(f"[cap_lock] poll_error lock_id={lock_id} holder={holder} poll={poll_no} type={type(e).__name__} msg={e}")
        time.sleep(0.2)
    waited_ms = int((time.monotonic() - start) * 1000)
    log.warning(f"[cap_lock] timeout lock_id={lock_id} holder={holder} waited_ms={waited_ms} date={lock_date} time={lock_time}")
    return None

def _release_capacity_lock(lock_id: str, holder: str):
    if not holder:
        return
    if not _init_firebase():
        return
    ref = db.reference(f"/sheet_locks/{lock_id}")
    now_ms = int(time.time() * 1000)
    def txn(current):
        if isinstance(current, dict) and current.get("holder") == holder:
            current["released"] = True
            current["released_by"] = holder
            current["released_ts"] = now_ms
            return current
        if current is None:
            return {"released": True, "released_by": holder, "released_ts": now_ms, "ts": 0}
        return current
    try:
        result = ref.transaction(txn)
        log.info(f"[cap_lock] released lock_id={lock_id} holder={holder} ts={now_ms} txn_result={result}")
        try:
            current = ref.get()
            log.info(f"[cap_lock] released_state lock_id={lock_id} current={current}")
        except Exception as e:
            log.warning(f"[cap_lock] released_state_error lock_id={lock_id} holder={holder} type={type(e).__name__} msg={e}")
    except Exception as e:
        log.warning(f"[cap_lock] release_error lock_id={lock_id} holder={holder} type={type(e).__name__} msg={e}")

def _wait_capacity_recalc(direction: str, date_iso: str, time_hm: str, station: str, expected_max: int, timeout_s: int = LOCK_WAIT_SECONDS):
    start = time.monotonic()
    last_seen = None
    polls = 0
    log.info(f"[cap_wait] start dir={direction} date={date_iso} time={time_hm} station={station} expected_max={expected_max}")
    while (time.monotonic() - start) < timeout_s:
        _invalidate_cap_sheet_cache()
        try:
            last_seen = lookup_capacity(direction, date_iso, time_hm, station)
            polls += 1
            log.info(f"[cap_wait] poll={polls} last_seen={last_seen} expected_max={expected_max}")
            if last_seen <= expected_max:
                log.info(f"[cap_wait] done polls={polls} last_seen={last_seen} expected_max={expected_max}")
                return True, last_seen
        except HTTPException as e:
            detail = getattr(e, "detail", "") or ""
            if isinstance(detail, str) and "capacity_not_found" in detail:
                last_seen = 0
                if last_seen <= expected_max:
                    log.info(f"[cap_wait] done_not_found polls={polls} last_seen=0 expected_max={expected_max}")
                    return True, last_seen
            else:
                last_seen = None
        except Exception as e:
            last_seen = None
            log.warning(f"[cap_wait] poll_error type={type(e).__name__} msg={e} dir={direction} date={date_iso} time={time_hm} station={station}")
            time.sleep(max(LOCK_POLL_INTERVAL, 5.0))
            continue
        time.sleep(LOCK_POLL_INTERVAL)
    log.warning(f"[cap_wait] timeout polls={polls} last_seen={last_seen} expected_max={expected_max}")
    return False, last_seen

def _finalize_capacity_lock(lock_id: str, holder: str, direction: str, date_iso: str, time_hm: str, station: str, expected_max: int):
    try:
        _invalidate_cap_sheet_cache()
        _wait_capacity_recalc(direction, date_iso, time_hm, station, expected_max)
    except Exception as e:
        log.warning(f"[cap_wait] finalize_error type={type(e).__name__} msg={e}")
    finally:
        _release_capacity_lock(lock_id, holder)

def _generate_booking_id_rtdb(today_iso: str) -> str:
    if not _init_firebase():
        raise RuntimeError("firebase_init_failed")
    date_key = (today_iso or "").strip()
    parts = date_key.split("-")
    yymmdd = ""
    if len(parts) == 3:
        yy = int(parts[0]) % 100
        yymmdd = f"{yy:02d}{int(parts[1]):02d}{int(parts[2]):02d}"
    else:
        compact = date_key.replace("-", "")
        yymmdd = compact[-6:] if len(compact) >= 6 else compact
    ref = db.reference(f"/booking_seq/{date_key}")
    def txn(current):
        cur = int(current or 0)
        return cur + 1
    seq = ref.transaction(txn)
    try:
        seq_int = int(seq or 0)
    except Exception:
        seq_int = 0
    return f"{yymmdd}{seq_int:02d}"

# ========== 母子車票管理（僅使用 Google Sheets）==========
def _get_sub_tickets_from_sheet(booking_id: str, values: List[List[str]], hmap: Dict[str, int]) -> List[Dict[str, Any]]:
    """
    從 Sheet 的 QRCode編碼（JSON）中讀取所有子票
    返回：子票列表，每個包含 sub_ticket_index, sub_ticket_pax, qr_content, status, checked_at
    """
    import json
    col = hmap.get("QRCode編碼")
    if not col:
        return []
    
    ci = col - 1
    sub_tickets = []
    
    # 查找對應的預約行
    for i, row in enumerate(values[HEADER_ROW_MAIN:], start=HEADER_ROW_MAIN + 1):
        if ci < len(row):
            booking_id_col = hmap.get("預約編號", 0) - 1
            if booking_id_col >= 0 and booking_id_col < len(row):
                if row[booking_id_col].strip() == booking_id:
                    qr_cell = (row[ci] or "").strip()
                    if qr_cell:
                        try:
                            qr_dict = json.loads(qr_cell)
                            if isinstance(qr_dict, dict):
                                for sub_key, sub_data in qr_dict.items():
                                    if sub_key.isdigit():
                                        sub_index = int(sub_key)
                                        if sub_index > 0:  # 排除母票（索引0）
                                            if isinstance(sub_data, dict):
                                                sub_tickets.append({
                                                    "sub_ticket_index": sub_index,
                                                    "sub_ticket_pax": sub_data.get("pax", 0),
                                                    "qr_content": sub_data.get("qr", ""),
                                                    "status": sub_data.get("status", "not_checked_in"),
                                                    "checked_at": sub_data.get("checked_at")
                                                })
                                            else:
                                                # 舊格式：直接是 QR Code 字符串
                                                sub_tickets.append({
                                                    "sub_ticket_index": sub_index,
                                                    "sub_ticket_pax": 0,  # 舊格式沒有 pax 信息
                                                    "qr_content": str(sub_data),
                                                    "status": "not_checked_in",
                                                    "checked_at": None
                                                })
                        except (json.JSONDecodeError, ValueError) as e:
                            log.warning(f"[sub_ticket] Failed to parse QRCode JSON for {booking_id}: {e}")
                    break
    
    # 排序：已上車的在前，未上車的在後，然後按索引排序
    return sorted(sub_tickets, key=lambda x: (x.get("status") != "checked_in", x.get("sub_ticket_index", 0)))

def _create_sub_tickets(booking_id: str, ticket_split: List[int], email: str, start_index: int = 1) -> List[Dict[str, Any]]:
    """
    創建子票（僅存儲到 Sheet，不寫入 Firebase）
    參數：
        booking_id: 預約編號
        ticket_split: 子票人數列表，例如 [2, 2, 2]
        email: 信箱（用於生成 QR Code）
        start_index: 起始索引（用於重新分票時避免索引衝突）
    返回：子票列表，每個包含 qr_content, sub_index, pax
    """
    sub_tickets = []
    created_at = _tz_now_str()
    
    for idx, pax in enumerate(ticket_split, start=0):
        sub_index = start_index + idx
        ticket_hash = _generate_ticket_hash(booking_id, sub_index, email)
        qr_content = f"FT:{booking_id}:{sub_index}:{ticket_hash}"
        
        sub_tickets.append({
            "qr_content": qr_content,
            "sub_index": sub_index,
            "pax": pax
        })
        log.info(f"[sub_ticket] Created ticket {sub_index} for booking {booking_id}, pax={pax}")
    
    return sub_tickets

def _re_split_tickets(booking_id: str, ticket_split: List[int], email: str, values: List[List[str]], hmap: Dict[str, int]) -> Tuple[List[Dict[str, Any]], int, int]:
    """
    重新分票：保留已上車的子票，為剩餘人數創建新子票（僅使用 Sheet）
    返回：(新子票列表, 已上車人數, 剩餘人數)
    """
    existing_tickets = _get_sub_tickets_from_sheet(booking_id, values, hmap)
    if not existing_tickets:
        raise ValueError("找不到現有子票，請使用首次分票功能")
    
    # 1. 分離已上車和未上車的子票
    checked_in_tickets = [t for t in existing_tickets if t.get("status") == "checked_in"]
    not_checked_in_tickets = [t for t in existing_tickets if t.get("status") != "checked_in"]
    
    # 2. 計算已上車人數和剩餘人數
    checked_in_pax = sum(t.get("sub_ticket_pax", 0) for t in checked_in_tickets)
    total_pax = sum(t.get("sub_ticket_pax", 0) for t in existing_tickets)
    remaining_pax = total_pax - checked_in_pax
    
    # 3. 驗證新分票總和 = 剩餘人數
    if sum(ticket_split) != remaining_pax:
        raise ValueError(f"新分票總和 ({sum(ticket_split)}) 必須等於剩餘人數 ({remaining_pax})")
    
    # 4. 為剩餘人數創建新子票（使用新的索引，從最大索引+1開始）
    max_existing_index = max([t.get("sub_ticket_index", 0) for t in checked_in_tickets], default=0)
    new_start_index = max_existing_index + 1
    
    new_sub_tickets = _create_sub_tickets(booking_id, ticket_split, email, start_index=new_start_index)
    
    log.info(f"[re_split] Re-split tickets for {booking_id}: checked_in={checked_in_pax}, remaining={remaining_pax}, new_tickets={len(new_sub_tickets)}")
    
    return new_sub_tickets, checked_in_pax, remaining_pax

def _create_mother_ticket(booking_id: str, email: str) -> str:
    """
    創建母票 QR Code（用於一次性核銷所有人）
    返回：母票 QR Code 內容
    """
    ticket_hash = _generate_ticket_hash(booking_id, 0, email)
    return f"FT:{booking_id}:0:{ticket_hash}"

def _update_sub_ticket_status_in_cache(booking_id: str, sub_index: int, checked_in_by: str = "driver") -> bool:
    """
    更新子票狀態到內存快取（用於批量寫回 Sheet）
    返回：True 如果成功加入快取，False 如果已存在
    """
    global CHECKIN_CACHE, CHECKIN_CACHE_LOCK
    with CHECKIN_CACHE_LOCK:
        if booking_id not in CHECKIN_CACHE:
            CHECKIN_CACHE[booking_id] = {}
        
        # 檢查是否已核銷
        if sub_index in CHECKIN_CACHE[booking_id]:
            return False  # 已經在快取中（已核銷）
        
        # 加入快取
        CHECKIN_CACHE[booking_id][sub_index] = {
            "status": "checked_in",
            "checked_at": _tz_now_str(),
            "checked_by": checked_in_by
        }
        log.info(f"[sub_ticket] Added to cache: {booking_id}:{sub_index}")
        return True

def _flush_checkin_cache() -> None:
    """批量寫回核銷快取到 Sheet"""
    global CHECKIN_CACHE, CHECKIN_CACHE_LOCK, _last_flush_time
    import json
    
    now = time.time()
    if now - _last_flush_time < CHECKIN_FLUSH_INTERVAL:
        return
    
    with CHECKIN_CACHE_LOCK:
        if not CHECKIN_CACHE:
            _last_flush_time = now
            return
        
        try:
            values, hmap = _get_sheet_data_main()
            ws = open_ws(SHEET_NAME_MAIN)
            
            # 按 booking_id 分組處理
            for booking_id, sub_tickets in CHECKIN_CACHE.items():
                # 查找對應的行
                rowno = None
                for i, row in enumerate(values[HEADER_ROW_MAIN:], start=HEADER_ROW_MAIN + 1):
                    booking_id_col = hmap.get("預約編號", 0) - 1
                    if booking_id_col >= 0 and booking_id_col < len(row):
                        if row[booking_id_col].strip() == booking_id:
                            rowno = i
                            break
                
                if not rowno:
                    log.warning(f"[flush_checkin] Booking {booking_id} not found in sheet")
                    continue
                
                # 讀取當前的 QRCode編碼 JSON
                qr_col = hmap.get("QRCode編碼", 0) - 1
                if qr_col < 0:
                    continue
                
                row_idx = rowno - 1
                row = values[row_idx] if 0 <= row_idx < len(values) else []
                qr_cell = (row[qr_col] or "").strip() if qr_col < len(row) else ""
                
                qr_dict = {}
                if qr_cell:
                    try:
                        qr_dict = json.loads(qr_cell)
                    except (json.JSONDecodeError, ValueError):
                        qr_dict = {}
                
                # 更新子票狀態
                updated = False
                for sub_index, checkin_data in sub_tickets.items():
                    sub_key = str(sub_index)
                    if sub_key in qr_dict:
                        if isinstance(qr_dict[sub_key], dict):
                            qr_dict[sub_key]["status"] = "checked_in"
                            qr_dict[sub_key]["checked_at"] = checkin_data["checked_at"]
                            updated = True
                
                # 計算總狀態
                if updated:
                    total_pax = 0
                    checked_pax = 0
                    for sub_key, sub_data in qr_dict.items():
                        if sub_key.isdigit() and isinstance(sub_data, dict):
                            pax = sub_data.get("pax", 0)
                            total_pax += pax
                            if sub_data.get("status") == "checked_in":
                                checked_pax += pax
                    
                    # 更新 Sheet
                    updates = {}
                    if total_pax > 0:
                        if checked_pax == 0:
                            ride_status = "未上車"
                        else:
                            ride_status = f"上車 ({checked_pax}/{total_pax})"
                        updates["乘車狀態"] = ride_status
                    
                    qr_json_str = json.dumps(qr_dict, ensure_ascii=False)
                    updates["QRCode編碼"] = qr_json_str
                    
                    if "最後操作時間" in hmap:
                        updates["最後操作時間"] = _tz_now_str() + " 已上車(司機)"
                    
                    # 批量更新
                    if updates:
                        data = []
                        for col_name, val in updates.items():
                            if col_name in hmap:
                                ci = hmap[col_name]
                                data.append({"range": gspread.utils.rowcol_to_a1(rowno, ci), "values": [[val]]})
                        if data:
                            ws.batch_update(data, value_input_option="USER_ENTERED")
                            log.info(f"[flush_checkin] Updated {booking_id} with {len(sub_tickets)} checkins")
            
            # 清空快取
            CHECKIN_CACHE = {}
            _last_flush_time = now
            _invalidate_sheet_cache()
            
        except Exception as e:
            log.error(f"[flush_checkin] Failed to flush cache: {e}")

def _checkin_all_sub_tickets(booking_id: str, values: List[List[str]], hmap: Dict[str, int], checked_in_by: str = "driver") -> int:
    """一次性核銷所有未上車的子票，返回核銷的子票數量"""
    sub_tickets = _get_sub_tickets_from_sheet(booking_id, values, hmap)
    if not sub_tickets:
        return 0
    checked_count = 0
    for ticket in sub_tickets:
        if ticket.get("status") != "checked_in":
            sub_index = ticket.get("sub_ticket_index")
            if sub_index and _update_sub_ticket_status_in_cache(booking_id, sub_index, checked_in_by):
                checked_count += 1
    return checked_count

def _calculate_mother_ticket_status(booking_id: str, values: List[List[str]], hmap: Dict[str, int]) -> Tuple[str, int, int]:
    """
    計算母票總狀態（從 Sheet JSON 讀取）
    返回：(狀態文字, 已上車人數, 總人數)
    狀態：未上車 / 上車 (X/Y)
    """
    sub_tickets = _get_sub_tickets_from_sheet(booking_id, values, hmap)
    if not sub_tickets:
        return "未上車", 0, 0
    
    # 檢查快取中的核銷狀態
    global CHECKIN_CACHE, CHECKIN_CACHE_LOCK
    with CHECKIN_CACHE_LOCK:
        cache_data = CHECKIN_CACHE.get(booking_id, {})
    
    total_pax = 0
    checked_pax = 0
    
    for t in sub_tickets:
        pax = t.get("sub_ticket_pax", 0)
        total_pax += pax
        
        sub_index = t.get("sub_ticket_index")
        # 檢查快取或 Sheet 中的狀態
        if sub_index in cache_data or t.get("status") == "checked_in":
            checked_pax += pax
    
    if checked_pax == 0:
        return "未上車", 0, total_pax
    else:
        # 統一格式：上車 (已上車人數/總人數)
        return f"上車 ({checked_pax}/{total_pax})", checked_pax, total_pax

def _sync_mother_ticket_status_to_sheet(booking_id: str, ws_main: gspread.Worksheet, hmap: Dict[str, int], rowno: int, values: List[List[str]]):
    """同步母票狀態到 Sheet"""
    try:
        status_text, checked_pax, total_pax = _calculate_mother_ticket_status(booking_id, values, hmap)
        if "乘車狀態" in hmap:
            ws_main.update_cell(rowno, hmap["乘車狀態"], status_text)
        log.info(f"[sub_ticket] Synced status for {booking_id}: {status_text}")
    except Exception as e:
        log.error(f"[sub_ticket] Failed to sync status for {booking_id}: {e}")

def _parse_qr_code(qr_content: str) -> Optional[Dict[str, Any]]:
    """
    解析 QR Code 內容
    返回：{"type": "mother"|"sub", "booking_id": str, "sub_index": int, "hash": str} 或 None
    """
    parts = qr_content.split(":")
    if len(parts) < 3 or parts[0] != "FT":
        return None
    booking_id = parts[1].strip()
    sub_index_str = parts[2].strip()
    hash_str = parts[3].strip() if len(parts) > 3 else ""
    
    try:
        sub_index = int(sub_index_str)
        return {
            "type": "mother" if sub_index == 0 else "sub",
            "booking_id": booking_id,
            "sub_index": sub_index,
            "hash": hash_str
        }
    except ValueError:
        return None

# ========== 郵件發送 ==========
def _send_email_gmail(to_email: str, subject: str, text_body: str, attachment: Optional[bytes] = None, attachment_filename: str = "ticket.png"):
    host = os.getenv("SMTP_HOST", "smtp.gmail.com")
    port = int(os.getenv("SMTP_PORT", "587"))
    user = os.getenv("SMTP_USER") or EMAIL_FROM_ADDR
    password = os.getenv("SMTP_PASS")
    if not password:
        raise RuntimeError("SMTP_PASS 未設定，無法寄信")
    msg = MIMEMultipart()
    msg["To"] = to_email
    msg["From"] = f"{EMAIL_FROM_NAME} <{EMAIL_FROM_ADDR}>"
    msg["Subject"] = subject
    msg.attach(MIMEText(text_body, "plain", "utf-8"))
    if attachment:
        part = MIMEBase("application", "octet-stream")
        part.set_payload(attachment)
        encoders.encode_base64(part)
        part.add_header("Content-Disposition", f'attachment; filename="{attachment_filename}"')
        msg.attach(part)
    with smtplib.SMTP(host, port) as server:
        server.ehlo()
        server.starttls()
        server.ehlo()
        server.login(user, password)
        server.sendmail(EMAIL_FROM_ADDR, [to_email], msg.as_string())

def _compose_mail_text(info: Dict[str, str], lang: str, kind: str) -> Tuple[str, str]:
    direction_map = {
        "zh": {"去程": "去程", "回程": "回程"},
        "en": {"去程": "Departure", "回程": "Return"},
        "ja": {"去程": "往路", "回程": "復路"},
        "ko": {"去程": "가는편", "回程": "오는편"},
    }
    raw_direction = info.get("direction", "")
    second_lang = lang if lang in ["en", "ja", "ko"] else "en"
    direction_zh = direction_map.get("zh", {}).get(raw_direction, raw_direction)
    direction_second = direction_map.get(second_lang, {}).get(raw_direction, raw_direction)
    subjects = {
        "book": {"zh": "汐止福泰大飯店接駁車預約確認", "en": "Forte Hotel Xizhi Shuttle Reservation Confirmation", "ja": "汐止フォルテホテル シャトル予約確認", "ko": "포르테 호텔 시즈 셔틀 예약 확인"},
        "modify": {"zh": "汐止福泰大飯店接駁車預約變更確認", "en": "Forte Hotel Xizhi Shuttle Reservation Updated", "ja": "汐止フォルテホテル シャトル予約変更完了", "ko": "포르테 호텔 시즈 셔틀 예약 변경 완료"},
        "cancel": {"zh": "汐止福泰大飯店接駁車預約已取消", "en": "Forte Hotel Xizhi Shuttle Reservation Canceled", "ja": "汐止フォルテホテル シャトル予約キャンセル", "ko": "포르테 호텔 시즈 셔틀 예약 취소됨"},
    }
    subject_zh = subjects[kind]["zh"]
    subject_second = subjects[kind].get(lang, subjects[kind]["en"])
    subject = f"{subject_zh} / {subject_second}"
    chinese_content = f"""尊敬的 {info.get('name','')} 貴賓，您好！

您的接駁車預約資訊：

預約編號：{info.get('booking_id','')}
預約班次：{info.get('date','')} {info.get('time','')} (GMT+8)
預約人數：{info.get('pax','')}
往返方向：{direction_zh}
上車站點：{info.get('pick','')}
下車站點：{info.get('drop','')}
手機：{info.get('phone','')}
信箱：{info.get('email','')}

請出示附件中的 QR Code 車票乘車。

如有任何問題，請致電 (02-2691-9222 #1)

汐止福泰大飯店 敬上
"""
    second_content_map = {
        "en": f"""Dear {info.get('name','')},

Your shuttle reservation details:

Reservation Number: {info.get('booking_id','')}
Reservation Time: {info.get('date','')} {info.get('time','')} (GMT+8)
Number of Guests: {info.get('pax','')}
Direction: {direction_second}
Pickup Location: {info.get('pick','')}
Dropoff Location: {info.get('drop','')}
Phone: {info.get('phone','')}
Email: {info.get('email','')}

Please present the attached QR code ticket for boarding.

If you have any questions, please call (02-2691-9222 #1)

Best regards,
Forte Hotel Xizhi
""",
        "ja": f"""{info.get('name','')} 様

シャトル予約の詳細：

予約番号：{info.get('booking_id','')}
便：{info.get('date','')} {info.get('time','')} (GMT+8)
人数：{info.get('pax','')}
方向：{direction_second}
乗車：{info.get('pick','')}
降車：{info.get('drop','')}
電話：{info.get('phone','')}
メール：{info.get('email','')}

添付のQRコードチケットを提示して乗車してください。

ご質問があれば、(02-2691-9222 #1) までお電話ください。

汐止フルオンホテル
""",
        "ko": f"""{info.get('name','')} 고객님,

셔틀 예약 내역：

예약번호: {info.get('booking_id','')}
시간: {info.get('date','')} {info.get('time','')} (GMT+8)
인원: {info.get('pax','')}
방향: {direction_second}
승차: {info.get('pick','')}
하차: {info.get('drop','')}
전화: {info.get('phone','')}
이메일: {info.get('email','')}

첨부된 QR 코드 티켓을 제시하고 탑승하세요.

문의사항이 있으면 (02-2691-9222 #1) 로 전화주세요.

포르테 호텔 시즈
"""
    }
    second_content = second_content_map.get(second_lang, second_content_map["en"])
    separator = "\n" + "="*50 + "\n"
    text_body = chinese_content + separator + second_content
    return subject, text_body

def _async_process_mail(kind: str, booking_id: str, booking_data: Dict[str, Any], qr_content: Optional[str], lang: str = "zh"):
    def _process():
        try:
            ws_main = open_ws(SHEET_NAME_MAIN)
            hmap = header_map_main(ws_main)
            headers = _sheet_headers(ws_main, HEADER_ROW_MAIN)
            rownos = _find_rows_by_pred(ws_main, headers, HEADER_ROW_MAIN, lambda r: r.get("預約編號") == booking_id)
            if not rownos:
                log.error(f"[mail:{kind}] 找不到預約編號 {booking_id} 對應的行")
                return
            rowno = rownos[0]
            qr_attachment: Optional[bytes] = None
            # ========== 母子車票：生成所有子票 QR Code ==========
            sub_tickets = booking_data.get("sub_tickets", [])
            mother_ticket = booking_data.get("mother_ticket")
            
            if kind in ("book", "modify"):
                if sub_tickets:
                    # 多子票模式：生成所有子票 QR Code（包含母票）
                    try:
                        from PIL import Image, ImageDraw, ImageFont
                        qr_images = []
                        for sub_ticket in sub_tickets:
                            qr_img = qrcode.make(sub_ticket["qr_content"])
                            qr_images.append((qr_img, f"子票{sub_ticket['sub_index']}({sub_ticket['pax']}人)"))
                        
                        # 添加母票 QR Code
                        if mother_ticket and mother_ticket.get("qr_content"):
                            qr_img = qrcode.make(mother_ticket["qr_content"])
                            qr_images.append((qr_img, "母票(全部)"))
                        
                        # 合併所有 QR Code 為一張圖片
                        if qr_images:
                            img_width = max(img.size[0] for img, _ in qr_images)
                            img_height = max(img.size[1] for img, _ in qr_images)
                            spacing = 20
                            total_height = len(qr_images) * (img_height + spacing) + spacing
                            combined_img = Image.new("RGB", (img_width + 200, total_height), "white")
                            draw = ImageDraw.Draw(combined_img)
                            
                            y_offset = spacing
                            for qr_img, label in qr_images:
                                combined_img.paste(qr_img, (spacing, y_offset))
                                # 添加標籤
                                try:
                                    font = ImageFont.truetype("arial.ttf", 16)
                                except:
                                    font = ImageFont.load_default()
                                draw.text((spacing + img_width + 10, y_offset + img_height // 2), label, fill="black", font=font)
                                y_offset += img_height + spacing
                            
                            buffer = io.BytesIO()
                            combined_img.save(buffer, format="PNG")
                            qr_attachment = buffer.getvalue()
                            log.info(f"[mail:{kind}] 生成 {len(qr_images)} 個 QR Code 附件成功（母子車票）")
                    except Exception as e:
                        log.error(f"[mail:{kind}] 生成子票 QR Code 附件失敗: {e}")
                        # 回退到單一 QR Code
                        if qr_content:
                            try:
                                qr_img = qrcode.make(qr_content)
                                buffer = io.BytesIO()
                                qr_img.save(buffer, format="PNG")
                                qr_attachment = buffer.getvalue()
                            except Exception as e2:
                                log.error(f"[mail:{kind}] 生成單一 QR Code 附件失敗: {e2}")
                elif qr_content:
                    # 單一子票模式（向後兼容）
                    try:
                        qr_img = qrcode.make(qr_content)
                        buffer = io.BytesIO()
                        qr_img.save(buffer, format="PNG")
                        qr_attachment = buffer.getvalue()
                        log.info(f"[mail:{kind}] 生成 QR Code 附件成功")
                    except Exception as e:
                        log.error(f"[mail:{kind}] 生成 QR Code 附件失敗: {e}")
            
            try:
                # 更新 Email 內容以包含子票信息
                email_text = booking_data.copy()
                if sub_tickets:
                    email_text["sub_tickets_info"] = "\n".join([
                        f"子票 {t['sub_index']}: {t['pax']}人 (QR Code: {t['qr_content']})"
                        for t in sub_tickets
                    ])
                    if mother_ticket and mother_ticket.get("qr_content"):
                        email_text["mother_ticket_info"] = f"母票（全部）: {mother_ticket['qr_content']}"
                
                subject, text_body = _compose_mail_text(email_text, lang, kind)
                _send_email_gmail(booking_data["email"], subject, text_body, attachment=qr_attachment, attachment_filename=f"shuttle_ticket_{booking_id}.png" if qr_attachment else None)
                mail_status = f"{_tz_now_str()} 寄信成功({kind})"
                log.info(f"[mail:{kind}] 預約 {booking_id} 寄信成功")
            except Exception as e:
                mail_status = f"{_tz_now_str()} 寄信失敗({kind}): {str(e)}"
                log.error(f"[mail:{kind}] 預約 {booking_id} 寄信失敗: {str(e)}")
            if "寄信狀態" in hmap:
                ws_main.update_acell(gspread.utils.rowcol_to_a1(rowno, hmap["寄信狀態"]), mail_status)
        except Exception as e:
            log.error(f"[mail:{kind}] 非同步處理預約 {booking_id} 時發生錯誤: {str(e)}")
    thread = threading.Thread(target=_process, daemon=True)
    thread.start()

def async_process_after_booking(booking_id: str, booking_data: Dict[str, Any], qr_content: str, lang: str = "zh"):
    _async_process_mail("book", booking_id, booking_data, qr_content, lang)

def async_process_after_modify(booking_id: str, booking_data: Dict[str, Any], qr_content: Optional[str], lang: str = "zh"):
    _async_process_mail("modify", booking_id, booking_data, qr_content, lang)

def async_process_after_cancel(booking_id: str, booking_data: Dict[str, Any], lang: str = "zh"):
    _async_process_mail("cancel", booking_id, booking_data, qr_content=None, lang=lang)

# ========== Pydantic Models ==========
class BookPayload(BaseModel):
    direction: str
    date: str
    station: str
    time: str
    identity: str
    checkIn: Optional[str] = None
    checkOut: Optional[str] = None
    diningDate: Optional[str] = None
    roomNumber: Optional[str] = None
    name: str
    phone: str
    email: str
    passengers: int = Field(..., ge=1, le=4)
    pickLocation: str
    dropLocation: str
    lang: str = Field("zh", pattern="^(zh|en|ja|ko)$")
    ticket_split: Optional[List[int]] = None  # 子票分配，例如 [2, 2, 2] 表示三個子票，每個2人
    
    @validator("direction")
    def _v_dir(cls, v):
        if v not in {"去程", "回程"}:
            raise ValueError("方向僅允許 去程 / 回程")
        return v
    
    @validator("ticket_split")
    def _v_ticket_split(cls, v, values):
        if v is None:
            return None
        if not isinstance(v, list) or len(v) == 0:
            raise ValueError("ticket_split 必須是非空列表")
        if any(not isinstance(x, int) or x < 1 for x in v):
            raise ValueError("ticket_split 每個元素必須是大於0的整數")
        total_passengers = values.get("passengers", 0)
        if sum(v) != total_passengers:
            raise ValueError(f"ticket_split 總和 ({sum(v)}) 必須等於 passengers ({total_passengers})")
        return v

class QueryPayload(BaseModel):
    booking_id: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None

class ModifyPayload(BaseModel):
    booking_id: str
    direction: Optional[str] = None
    date: Optional[str] = None
    station: Optional[str] = None
    time: Optional[str] = None
    passengers: Optional[int] = Field(None, ge=1, le=4)
    pickLocation: Optional[str] = None
    dropLocation: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    lang: str = Field("zh", pattern="^(zh|en|ja|ko)$")

class DeletePayload(BaseModel):
    booking_id: str
    lang: str = Field("zh", pattern="^(zh|en|ja|ko)$")

class SplitTicketPayload(BaseModel):
    booking_id: str
    ticket_split: List[int] = Field(..., min_items=1)  # 至少1張票（可以是1張，表示合併）
    lang: str = Field("zh", pattern="^(zh|en|ja|ko)$")
    
    @validator("ticket_split")
    def _v_ticket_split(cls, v):
        if not isinstance(v, list) or len(v) < 1:
            raise ValueError("ticket_split 必須至少包含1個元素")
        if any(not isinstance(x, int) or x < 1 for x in v):
            raise ValueError("ticket_split 每個元素必須是大於0的整數")
        return v

class CheckInPayload(BaseModel):
    code: Optional[str] = None
    booking_id: Optional[str] = None

class MailPayload(BaseModel):
    booking_id: str
    lang: str = Field("zh", pattern="^(zh|en|ja|ko)$")
    kind: str = Field(..., pattern="^(book|modify|cancel)$")
    ticket_png_base64: Optional[str] = None

class OpsRequest(BaseModel):
    action: str
    data: Dict[str, Any]

class DriverTrip(BaseModel):
    trip_id: str
    date: str
    time: str
    total_pax: int

class DriverPassenger(BaseModel):
    trip_id: str
    station: str
    updown: str
    booking_id: str
    name: str
    phone: str
    room: str
    pax: int
    status: str
    direction: Optional[str] = None
    qrcode: str

class DriverAllPassenger(BaseModel):
    booking_id: str
    main_datetime: str
    depart_time: str
    name: str
    phone: str
    room: str
    pax: int
    ride_status: str
    direction: str
    hotel_go: str
    mrt: str
    train: str
    mall: str
    hotel_back: str

class DriverAllData(BaseModel):
    trips: List[DriverTrip]
    trip_passengers: List[DriverPassenger]
    passenger_list: List[DriverAllPassenger]

class DriverCheckinRequest(BaseModel):
    qrcode: str

class DriverCheckinResponse(BaseModel):
    status: str
    message: str
    booking_id: Optional[str] = None
    name: Optional[str] = None
    pax: Optional[int] = None
    station: Optional[str] = None
    main_datetime: Optional[str] = None
    sub_index: Optional[int] = None  # 新增：子票索引
    checked_pax: Optional[int] = None  # 新增：已上車總人數
    total_pax: Optional[int] = None  # 新增：總人數
    ride_status: Optional[str] = None  # 新增：完整狀態（例如 "上車 (3/5)"）

class DriverLocation(BaseModel):
    lat: float
    lng: float
    timestamp: float
    trip_id: Optional[str] = None

class BookingIdRequest(BaseModel):
    booking_id: str

class TripStatusRequest(BaseModel):
    main_datetime: str
    status: str

class QrInfoRequest(BaseModel):
    qrcode: str

class QrInfoResponse(BaseModel):
    booking_id: Optional[str]
    name: Optional[str]
    main_datetime: Optional[str]
    ride_status: Optional[str]
    station_up: Optional[str]
    station_down: Optional[str]

class GoogleTripStartRequest(BaseModel):
    main_datetime: str
    driver_role: Optional[str] = None
    stops: Optional[List[str]] = None

class GoogleTripStartResponse(BaseModel):
    trip_id: Optional[str] = None
    share_url: Optional[str] = None
    stops: Optional[List[Dict[str, float]]] = None

class GoogleTripCompleteRequest(BaseModel):
    trip_id: str
    driver_role: Optional[str] = None
    main_datetime: Optional[str] = None

class SystemStatusRequest(BaseModel):
    enabled: bool

class UpdateStationRequest(BaseModel):
    trip_id: str
    current_station: str

# ========== FastAPI 應用初始化 ==========
app = FastAPI(title="Unified Shuttle System API", version="2.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://shuttle-web-509045429779.asia-east1.run.app",
        "https://shuttle-web-ywrjpvbwya-de.a.run.app",
        "http://localhost:8080",
        "*",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.on_event("startup")
async def startup_event():
    log.info("Application startup: Ensuring Firebase paths exist")
    _init_firebase()

# 啟動定時刷新核銷快取的後台線程
def _start_checkin_cache_flusher():
    """啟動定時刷新核銷快取的後台線程"""
    def flush_loop():
        while True:
            try:
                time.sleep(CHECKIN_FLUSH_INTERVAL)
                _flush_checkin_cache()
            except Exception as e:
                log.error(f"[flush_loop] Error: {e}")
    
    threading.Thread(target=flush_loop, daemon=True).start()
    log.info("[checkin_cache] Started background flusher thread")

# 啟動後台線程
_start_checkin_cache_flusher()

@app.get("/health")
@app.get("/api/health")
def health():
    return {"status": "ok", "time": _tz_now_str()}

# ========== Booking API 端點 ==========
@app.get("/api/sheet")
def get_sheet_data(sheet: str = DEFAULT_SHEET, range: Optional[str] = None):
    if range:
        range_name = f"{sheet}!{range}"
    else:
        range_name = f"{sheet}!{DEFAULT_RANGE}"
    cached_values = _get_cached_sheet_data(sheet, range_name)
    if cached_values is not None:
        return cached_values
    try:
        creds, _ = default(scopes=["https://www.googleapis.com/auth/spreadsheets.readonly"])
        service = build("sheets", "v4", credentials=creds)
        result = service.spreadsheets().values().get(spreadsheetId=SPREADSHEET_ID, range=range_name).execute()
        values = result.get("values", [])
        _set_cached_sheet_data(sheet, range_name, values)
        return values
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/realtime/location")
def api_realtime_location():
    try:
        if not _init_firebase():
            raise HTTPException(status_code=500, detail="Firebase initialization failed")
        gps_system_enabled = None
        try:
            cached_gps_enabled = _get_cached_sheet_data("系統", "系統!E19")
            if cached_gps_enabled is None:
                creds, _ = default(scopes=["https://www.googleapis.com/auth/spreadsheets.readonly"])
                service = build("sheets", "v4", credentials=creds)
                result = service.spreadsheets().values().get(spreadsheetId=SPREADSHEET_ID, range="系統!E19").execute()
                values = result.get("values", [])
                if values and len(values) > 0 and len(values[0]) > 0:
                    e19_value = (values[0][0] or "").strip().lower()
                    gps_system_enabled = e19_value in ("true", "t", "yes", "1")
                    _set_cached_sheet_data("系統", "系統!E19", values)
            else:
                if cached_gps_enabled and len(cached_gps_enabled) > 0 and len(cached_gps_enabled[0]) > 0:
                    e19_value = (cached_gps_enabled[0][0] or "").strip().lower()
                    gps_system_enabled = e19_value in ("true", "t", "yes", "1")
        except Exception:
            pass
        if gps_system_enabled is None:
            gps_system_enabled = db.reference("/gps_system_enabled").get()
        if gps_system_enabled is None:
            gps_system_enabled = False
        driver_location = db.reference("/driver_location").get() or {}
        current_trip_id = db.reference("/current_trip_id").get() or ""
        current_trip_status = db.reference("/current_trip_status").get() or ""
        current_trip_datetime = db.reference("/current_trip_datetime").get() or ""
        current_trip_route = db.reference("/current_trip_route").get() or {}
        current_trip_stations = db.reference("/current_trip_stations").get() or {}
        current_trip_station = db.reference("/current_trip_station").get() or ""
        current_trip_start_time = db.reference("/current_trip_start_time").get() or 0
        current_trip_completed_stops = db.reference("/current_trip_completed_stops").get() or []
        last_trip_datetime = db.reference("/last_trip_datetime").get() or ""
        try:
            if current_trip_status == "active" and current_trip_start_time:
                now_ms = int(time.time() * 1000)
                elapsed_ms = now_ms - int(current_trip_start_time)
                if elapsed_ms >= AUTO_SHUTDOWN_MS:
                    try:
                        if current_trip_id:
                            db.reference(f"/trip/{current_trip_id}/route").delete()
                    except Exception:
                        pass
                    db.reference("/current_trip_status").set("ended")
                    if current_trip_datetime:
                        db.reference("/last_trip_datetime").set(current_trip_datetime)
                    db.reference("/current_trip_id").set("")
                    db.reference("/current_trip_route").set({})
                    db.reference("/current_trip_datetime").set("")
                    db.reference("/current_trip_stations").set({})
                    current_trip_status = "ended"
                    if current_trip_datetime:
                        last_trip_datetime = current_trip_datetime
            if current_trip_status == "active":
                driver_location_updated_at = driver_location.get("updated_at") if driver_location else None
                if driver_location_updated_at and current_trip_start_time:
                    try:
                        updated_dt = datetime.strptime(driver_location_updated_at, "%Y-%m-%d %H:%M:%S")
                        now_dt = datetime.now()
                        elapsed_seconds = (now_dt - updated_dt).total_seconds()
                        if elapsed_seconds >= GPS_TIMEOUT_SECONDS:
                            now_ms = int(time.time() * 1000)
                            elapsed_ms = now_ms - int(current_trip_start_time)
                            if elapsed_ms >= AUTO_SHUTDOWN_MS:
                                try:
                                    db.reference("/current_trip_path_history").set([])
                                except Exception:
                                    pass
                                db.reference("/current_trip_status").set("ended")
                                if current_trip_datetime:
                                    db.reference("/last_trip_datetime").set(current_trip_datetime)
                                db.reference("/current_trip_id").set("")
                                db.reference("/current_trip_route").set({})
                                db.reference("/current_trip_datetime").set("")
                                db.reference("/current_trip_stations").set({})
                                db.reference("/current_trip_path_history").set([])
                                current_trip_status = "ended"
                                if current_trip_datetime:
                                    last_trip_datetime = current_trip_datetime
                    except Exception:
                        pass
        except Exception:
            pass
        current_trip_path_history = []
        try:
            if current_trip_id:
                path_history_ref = db.reference("/current_trip_path_history")
                current_trip_path_history = path_history_ref.get() or []
        except Exception:
            pass
        return {
            "gps_system_enabled": bool(gps_system_enabled),
            "driver_location": driver_location,
            "current_trip_id": current_trip_id,
            "current_trip_status": current_trip_status,
            "current_trip_datetime": current_trip_datetime,
            "current_trip_route": current_trip_route,
            "current_trip_stations": current_trip_stations,
            "current_trip_station": current_trip_station,
            "current_trip_start_time": int(current_trip_start_time) if current_trip_start_time else 0,
            "current_trip_completed_stops": current_trip_completed_stops,
            "current_trip_path_history": current_trip_path_history,
            "last_trip_datetime": last_trip_datetime
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ========== Booking Processor ==========
class BookingProcessor:
    def __init__(self):
        self.processing_lock = threading.Lock()
    
    def prepare_booking_row(self, p: BookPayload, booking_id: str, qr_content: str, headers: List[str], hmap: Dict[str, int], ticket_split_str: str = "") -> List[str]:
        time_hm = _time_hm_from_any(p.time)
        car_display = _display_trip_str(p.date, time_hm)
        pk_idx, dp_idx, seg_str = _compute_indices_and_segments(p.pickLocation, p.dropLocation)
        date_obj = datetime.strptime(p.date, "%Y-%m-%d")
        car_datetime = date_obj.strftime("%Y/%m/%d") + " " + time_hm
        main_departure = _compute_main_departure_datetime(p.direction, p.pickLocation, p.date, time_hm)
        newrow = [""] * len(headers)
        identity_simple = "住宿" if p.identity == "hotel" else "用餐"
        def setv(row_arr: List[str], col: str, v: Any):
            if col in hmap and 1 <= hmap[col] <= len(row_arr):
                row_arr[hmap[col] - 1] = str(v)
        setv(newrow, "申請日期", _tz_now_str())
        setv(newrow, "預約狀態", BOOKED_TEXT)
        setv(newrow, "預約編號", booking_id)
        setv(newrow, "往返", p.direction)
        setv(newrow, "日期", p.date)
        setv(newrow, "班次", time_hm)
        setv(newrow, "車次", car_display)
        setv(newrow, "車次-日期時間", car_datetime)
        setv(newrow, "主班次時間", main_departure)
        setv(newrow, "上車地點", p.pickLocation)
        setv(newrow, "下車地點", p.dropLocation)
        setv(newrow, "姓名", p.name)
        setv(newrow, "手機", p.phone)
        setv(newrow, "信箱", p.email)
        setv(newrow, "預約人數", p.passengers)
        setv(newrow, "乘車狀態", "")
        setv(newrow, "身分", identity_simple)
        setv(newrow, "房號", p.roomNumber or "")
        setv(newrow, "入住日期", p.checkIn or "")
        setv(newrow, "退房日期", p.checkOut or "")
        setv(newrow, "用餐日期", p.diningDate or "")
        setv(newrow, "上車索引", pk_idx)
        setv(newrow, "下車索引", dp_idx)
        setv(newrow, "涉及路段範圍", seg_str)
        setv(newrow, "QRCode編碼", qr_content)
        setv(newrow, "寄信狀態", "處理中")
        return newrow

booking_processor = BookingProcessor()

# ========== Booking Manager 端點 ==========
@app.options("/api/ops")
@app.options("/api/ops/")
def ops_options():
    return Response(status_code=204)

@app.post("/api/ops")
@app.post("/api/ops/")
def ops(req: OpsRequest):
    action = (req.action or "").strip().lower()
    data = req.data or {}
    log.info(f"OPS action={action} payload={data}")
    try:
        if action == "query":
            p = QueryPayload(**data)
            if not (p.booking_id or p.phone or p.email):
                raise HTTPException(400, "至少提供 booking_id / phone / email 其中一項")
            all_values, hmap = _get_sheet_data_main()
            if not all_values:
                return []
            def get(row: List[str], key: str) -> str:
                return row[hmap[key] - 1] if key in hmap and len(row) >= hmap[key] else ""
            now = _tz_now()
            one_month_ago = now - timedelta(days=31)
            results: List[Dict[str, Any]] = []
            for row in all_values[HEADER_ROW_MAIN:]:
                car_dt_str = get(row, "車次-日期時間")
                date_iso: str = ""
                time_hm: str = ""
                if car_dt_str:
                    try:
                        parts = car_dt_str.strip().split()
                        if parts:
                            date_iso = parts[0].replace("/", "-")
                            if len(parts) > 1:
                                time_hm = _time_hm_from_any(parts[1])
                        else:
                            date_iso = ""
                    except Exception:
                        date_iso = get(row, "日期")
                        time_hm = _time_hm_from_any(get(row, "班次"))
                else:
                    date_iso = get(row, "日期")
                    time_hm = _time_hm_from_any(get(row, "班次"))
                try:
                    d = datetime.strptime(date_iso, "%Y-%m-%d")
                except Exception:
                    d = now
                if d < one_month_ago:
                    continue
                if p.booking_id and p.booking_id != get(row, "預約編號"):
                    continue
                if p.phone and p.phone != get(row, "手機"):
                    continue
                if p.email:
                    row_email = get(row, "信箱").strip().lower()
                    query_email = p.email.strip().lower()
                    if query_email != row_email:
                        continue
                rec = {k: get(row, k) for k in hmap}
                if date_iso:
                    rec["日期"] = date_iso
                if time_hm:
                    rec["班次"] = time_hm
                    rec["車次"] = _display_trip_str(date_iso, time_hm)
                if rec.get("櫃台審核", "").lower() == "n":
                    rec["預約狀態"] = "已拒絕"
                
                # ========== 添加母子車票信息 ==========
                booking_id = rec.get("預約編號", "")
                if booking_id:
                    try:
                        sub_tickets = _get_sub_tickets_from_sheet(booking_id, values, hmap)
                        if sub_tickets:
                            # 生成子票編號後綴（A, B, C...）
                            def get_suffix(index: int) -> str:
                                return chr(64 + index)  # 65='A', 66='B', etc.
                            
                            rec["sub_tickets"] = [
                                {
                                    "sub_index": t.get("sub_ticket_index"),
                                    "booking_id": f"{booking_id}_{get_suffix(t.get('sub_ticket_index', 1))}",  # 例如：26021205_A
                                    "pax": t.get("sub_ticket_pax", 0),
                                    "status": t.get("status", "not_checked_in"),
                                    "qr_content": t.get("qr_content", ""),
                                    "qr_url": f"{BASE_URL}/api/qr/{urllib.parse.quote(t.get('qr_content', ''))}" if t.get("qr_content") else ""
                                }
                                for t in sub_tickets
                            ]
                            # 更新乘車狀態（如果存在子票）
                            status_text, _, _ = _calculate_mother_ticket_status(booking_id, values, hmap)
                            if status_text and status_text != "未上車":
                                rec["乘車狀態"] = status_text
                    except Exception as e:
                        log.warning(f"[query] Failed to get sub_tickets for {booking_id}: {e}")
                
                results.append(rec)
            log.info(f"query results count={len(results)}")
            return results

        ws_main = open_ws(SHEET_NAME_MAIN)
        hmap = header_map_main(ws_main)
        headers = _sheet_headers(ws_main, HEADER_ROW_MAIN)

        def setv(row_arr: List[str], col: str, v: Any):
            if col in hmap and 1 <= hmap[col] <= len(row_arr):
                if isinstance(v, (int, float)):
                    row_arr[hmap[col] - 1] = v
                elif isinstance(v, str):
                    row_arr[hmap[col] - 1] = v
                else:
                    row_arr[hmap[col] - 1] = str(v)

        row_cache: Dict[int, List[str]] = {}

        def _get_row_values(rowno: int) -> List[str]:
            if rowno not in row_cache:
                try:
                    row_cache[rowno] = ws_main.row_values(rowno) or []
                except Exception:
                    row_cache[rowno] = []
            return row_cache[rowno]

        def get_by_rowno(rowno: int, key: str) -> str:
            if key not in hmap:
                return ""
            row = _get_row_values(rowno)
            idx = hmap[key] - 1
            if idx < 0 or idx >= len(row):
                return ""
            return row[idx] or ""

        if action == "book":
            p = BookPayload(**data)
            time_hm = _time_hm_from_any(p.time)
            station_for_cap = _normalize_station_for_capacity(p.direction, p.pickLocation, p.dropLocation)
            lock_id = _lock_id_for_capacity(p.date, time_hm)
            lock_holder = _acquire_capacity_lock(lock_id, p.date, time_hm)
            if not lock_holder:
                raise HTTPException(503, "系統繁忙，請稍後再試")
            rem = None
            wrote = False
            defer_release = False
            try:
                rem = lookup_capacity(p.direction, p.date, time_hm, station_for_cap)
                if int(p.passengers) > int(rem):
                    raise HTTPException(409, f"capacity_exceeded:{p.passengers}>{rem}")
                today_iso = _today_iso_taipei()
                try:
                    booking_id = _generate_booking_id_rtdb(today_iso)
                except Exception as e:
                    log.warning(f"[booking_id] rtdb_failed type={type(e).__name__} msg={e}")
                    raise HTTPException(503, "暫時無法產生預約編號，請稍後再試")
                
                # ========== 母子車票邏輯 ==========
                ticket_split = p.ticket_split if p.ticket_split else [p.passengers]  # 如果未提供，默認單一子票
                sub_tickets = []
                mother_qr_content = None
                
                if len(ticket_split) > 1:
                    # 多子票模式：創建子票並生成母票
                    try:
                        sub_tickets = _create_sub_tickets(booking_id, ticket_split, p.email)
                        mother_qr_content = _create_mother_ticket(booking_id, p.email)
                        log.info(f"[sub_ticket] Created {len(sub_tickets)} sub-tickets for booking {booking_id}")
                    except Exception as e:
                        log.error(f"[sub_ticket] Failed to create sub-tickets: {e}")
                        raise HTTPException(500, f"創建子票失敗: {str(e)}")
                    # 使用母票 QR Code 作為主 QR Code
                    qr_content = mother_qr_content
                else:
                    # 單一子票模式（向後兼容）：使用舊格式
                    em6 = _email_hash6(p.email)
                    qr_content = f"FT:{booking_id}:{em6}"
                
                qr_url = f"{BASE_URL}/api/qr/{urllib.parse.quote(qr_content)}"
                
                # 準備 Sheet 行（包含子票配置信息）
                ticket_split_str = ",".join(str(x) for x in ticket_split) if len(ticket_split) > 1 else ""
                newrow = booking_processor.prepare_booking_row(p, booking_id, qr_content, headers, hmap, ticket_split_str)
                ws_main.append_row(newrow, value_input_option="USER_ENTERED")
                wrote = True
                log.info(f"book appended booking_id={booking_id}, ticket_split={ticket_split}")
                _invalidate_sheet_cache()
                expected_max = max(0, int(rem) - int(p.passengers))
                defer_release = True
                threading.Thread(target=_finalize_capacity_lock, args=(lock_id, lock_holder, p.direction, p.date, time_hm, station_for_cap, expected_max), daemon=True).start()
            finally:
                if not defer_release:
                    _release_capacity_lock(lock_id, lock_holder)
            
            # 準備回應數據
            response_data = {
                "status": "success",
                "bookingId": booking_id,
                "booking_id": booking_id,
                "qrUrl": qr_url,
                "qr_url": qr_url,
                "qrContent": qr_content,
                "qr_content": qr_content,
            }
            
            # 如果有多個子票，返回所有子票信息
            if sub_tickets:
                response_data["sub_tickets"] = [
                    {
                        "sub_index": t["sub_index"],
                        "pax": t["pax"],
                        "qr_content": t["qr_content"],
                        "qr_url": f"{BASE_URL}/api/qr/{urllib.parse.quote(t['qr_content'])}"
                    }
                    for t in sub_tickets
                ]
                response_data["mother_ticket"] = {
                    "qr_content": mother_qr_content,
                    "qr_url": f"{BASE_URL}/api/qr/{urllib.parse.quote(mother_qr_content)}"
                }
            
            # 準備 Email 數據（包含所有子票 QR Code）
            booking_info = {
                "booking_id": booking_id,
                "date": p.date,
                "time": time_hm,
                "direction": p.direction,
                "pick": p.pickLocation,
                "drop": p.dropLocation,
                "name": p.name,
                "phone": p.phone,
                "email": p.email,
                "pax": str(p.passengers),
                "qr_content": qr_content,
                "qr_url": qr_url,
                "sub_tickets": sub_tickets,
                "mother_ticket": {"qr_content": mother_qr_content} if mother_qr_content else None
            }
            async_process_after_booking(booking_id, booking_info, qr_content, p.lang)
            return response_data

        elif action == "modify":
            p = ModifyPayload(**data)
            rownos = _find_rows_by_pred(ws_main, headers, HEADER_ROW_MAIN, lambda r: r.get("預約編號") == p.booking_id)
            if not rownos:
                raise HTTPException(404, "找不到此預約編號")
            rowno = rownos[0]
            old_dir = get_by_rowno(rowno, "往返")
            old_date = get_by_rowno(rowno, "日期")
            old_car_dt = get_by_rowno(rowno, "車次-日期時間")
            if old_car_dt:
                parts = old_car_dt.strip().split()
                old_time = _time_hm_from_any(parts[1] if len(parts) > 1 else parts[0])
            else:
                old_time = _time_hm_from_any(get_by_rowno(rowno, "班次"))
            old_pick = get_by_rowno(rowno, "上車地點")
            old_drop = get_by_rowno(rowno, "下車地點")
            try:
                confirm_pax = (get_by_rowno(rowno, "確認人數") or "").strip()
                old_pax = int(confirm_pax) if confirm_pax else int(get_by_rowno(rowno, "預約人數") or "1")
            except Exception:
                old_pax = 1
            new_dir = p.direction or old_dir
            new_date = p.date or old_date
            new_time = _time_hm_from_any(p.time or old_time)
            new_pick = p.pickLocation or old_pick
            new_drop = p.dropLocation or old_drop
            new_pax = int(p.passengers if p.passengers is not None else old_pax)
            station_for_cap_new = _normalize_station_for_capacity(new_dir, new_pick, new_drop)
            same_trip = (new_dir, new_date, new_time, _normalize_station_for_capacity(old_dir, old_pick, old_drop)) == (old_dir, old_date, _time_hm_from_any(old_time), _normalize_station_for_capacity(old_dir, old_pick, old_drop))
            consume = 0
            if same_trip:
                delta = new_pax - old_pax
                consume = delta if delta > 0 else 0
            else:
                consume = new_pax
            lock_holder = None
            lock_id = None
            rem = None
            wrote = False
            defer_release = False
            if consume > 0:
                lock_id = _lock_id_for_capacity(new_date, new_time)
                lock_holder = _acquire_capacity_lock(lock_id, new_date, new_time)
                if not lock_holder:
                    raise HTTPException(503, "系統繁忙，請稍後再試")
            try:
                if consume > 0:
                    rem = lookup_capacity(new_dir, new_date, new_time, station_for_cap_new)
                    if same_trip:
                        delta = new_pax - old_pax
                        if delta > 0 and delta > rem:
                            raise HTTPException(409, f"capacity_exceeded_delta:{delta}>{rem}")
                    else:
                        if new_pax > rem:
                            raise HTTPException(409, f"capacity_exceeded:{new_pax}>{rem}")
                updates: Dict[str, str] = {}
                time_hm = new_time
                car_display = _display_trip_str(new_date, time_hm) if (new_date and time_hm) else None
                if new_date and new_time:
                    date_obj = datetime.strptime(new_date, "%Y-%m-%d")
                    car_datetime = date_obj.strftime("%Y/%m/%d") + " " + new_time
                    updates["車次-日期時間"] = car_datetime
                    main_departure = _compute_main_departure_datetime(new_dir, new_pick, new_date, new_time)
                    updates["主班次時間"] = main_departure
                pk_idx = dp_idx = None
                seg_str = None
                if new_pick and new_drop:
                    pk_idx, dp_idx, seg_str = _compute_indices_and_segments(new_pick, new_drop)
                updates["預約狀態"] = BOOKED_TEXT
                updates["預約人數"] = str(new_pax)
                if "備註" in hmap:
                    current_note = ws_main.cell(rowno, hmap["備註"]).value or ""
                    new_note = f"{_tz_now_str()} 已修改"
                    updates["備註"] = f"{current_note}; {new_note}" if current_note else new_note
                updates["往返"] = new_dir
                updates["日期"] = new_date
                if time_hm:
                    updates["班次"] = time_hm
                if car_display:
                    updates["車次"] = car_display
                updates["上車地點"] = new_pick
                updates["下車地點"] = new_drop
                if p.phone:
                    updates["手機"] = p.phone
                old_email = get_by_rowno(rowno, "信箱")
                final_email = p.email or old_email
                qr_content: Optional[str] = None
                if p.email:
                    updates["信箱"] = p.email
                if final_email:
                    em6 = _email_hash6(final_email)
                    qr_content = f"FT:{p.booking_id}:{em6}"
                    updates["QRCode編碼"] = qr_content
                if pk_idx is not None:
                    updates["上車索引"] = str(pk_idx)
                if dp_idx is not None:
                    updates["下車索引"] = str(dp_idx)
                if seg_str is not None:
                    updates["涉及路段範圍"] = seg_str
                if "最後操作時間" in hmap:
                    updates["最後操作時間"] = _tz_now_str() + " 已修改"
                updates["寄信狀態"] = "處理中"
                batch_updates = []
                for col_name, value in updates.items():
                    if col_name in hmap:
                        batch_updates.append({"range": gspread.utils.rowcol_to_a1(rowno, hmap[col_name]), "values": [[value]]})
                if batch_updates:
                    ws_main.batch_update(batch_updates, value_input_option="USER_ENTERED")
                    wrote = True
                log.info(f"modify updated booking_id={p.booking_id}")
                _invalidate_sheet_cache()
                if consume > 0 and rem is not None and wrote and lock_holder and lock_id:
                    expected_max = max(0, int(rem) - int(consume))
                    defer_release = True
                    threading.Thread(target=_finalize_capacity_lock, args=(lock_id, lock_holder, new_dir, new_date, new_time, station_for_cap_new, expected_max), daemon=True).start()
                response_data = {"status": "success", "bookingId": p.booking_id, "booking_id": p.booking_id}
                booking_info = {"booking_id": p.booking_id, "date": new_date, "time": new_time, "direction": new_dir, "pick": new_pick, "drop": new_drop, "name": get_by_rowno(rowno, "姓名"), "phone": p.phone or get_by_rowno(rowno, "手機"), "email": final_email, "pax": str(new_pax), "qr_content": qr_content, "qr_url": f"{BASE_URL}/api/qr/{urllib.parse.quote(qr_content)}" if qr_content else ""}
                async_process_after_modify(p.booking_id, booking_info, qr_content, p.lang)
                return response_data
            finally:
                if not defer_release and lock_holder:
                    _release_capacity_lock(lock_id, lock_holder)

        elif action == "delete":
            p = DeletePayload(**data)
            rownos = _find_rows_by_pred(ws_main, headers, HEADER_ROW_MAIN, lambda r: r.get("預約編號") == p.booking_id)
            if not rownos:
                raise HTTPException(404, "找不到此預約編號")
            rowno = rownos[0]
            updates: Dict[str, str] = {}
            if "預約狀態" in hmap:
                updates["預約狀態"] = CANCELLED_TEXT
            if "備註" in hmap:
                current_note = ws_main.cell(rowno, hmap["備註"]).value or ""
                new_note = f"{_tz_now_str()} 已取消"
                updates["備註"] = f"{current_note}; {new_note}" if current_note else new_note
            if "最後操作時間" in hmap:
                updates["最後操作時間"] = _tz_now_str() + " 已刪除"
            updates["寄信狀態"] = "處理中"
            batch_updates = []
            for col_name, value in updates.items():
                if col_name in hmap:
                    batch_updates.append({"range": gspread.utils.rowcol_to_a1(rowno, hmap[col_name]), "values": [[value]]})
            if batch_updates:
                ws_main.batch_update(batch_updates, value_input_option="USER_ENTERED")
            log.info(f"delete updated booking_id={p.booking_id}")
            _invalidate_sheet_cache()
            response_data = {"status": "success", "booking_id": p.booking_id}
            booking_info = {"booking_id": p.booking_id, "date": get_by_rowno(rowno, "日期"), "time": _time_hm_from_any(get_by_rowno(rowno, "班次")), "direction": get_by_rowno(rowno, "往返"), "pick": get_by_rowno(rowno, "上車地點"), "drop": get_by_rowno(rowno, "下車地點"), "name": get_by_rowno(rowno, "姓名"), "phone": get_by_rowno(rowno, "手機"), "email": get_by_rowno(rowno, "信箱"), "pax": (get_by_rowno(rowno, "確認人數") or get_by_rowno(rowno, "預約人數") or "1")}
            async_process_after_cancel(p.booking_id, booking_info, p.lang)
            return response_data

        elif action == "check_in":
            p = CheckInPayload(**data)
            if not (p.code or p.booking_id):
                raise HTTPException(400, "需提供 code 或 booking_id")
            
            # ========== 母子車票上車邏輯 ==========
            qr_code = p.code or ""
            booking_id_from_qr = None
            
            # 解析 QR Code（支持新格式）
            if qr_code:
                parsed = _parse_qr_code(qr_code)
                if parsed:
                    booking_id_from_qr = parsed["booking_id"]
                    ticket_type = parsed["type"]
                    sub_index = parsed["sub_index"]
                    
                    # 查找母票記錄
                    rownos = _find_rows_by_pred(ws_main, headers, HEADER_ROW_MAIN, lambda r: r.get("預約編號") == booking_id_from_qr)
                    if not rownos:
                        raise HTTPException(404, "找不到對應的預約編號")
                    rowno = rownos[0]
                    
                    # 子票上車
                    if ticket_type == "sub":
                        if _update_sub_ticket_status_in_cache(booking_id_from_qr, sub_index, "check_in_api"):
                            log.info(f"[sub_ticket] Checked in sub-ticket {booking_id_from_qr}:{sub_index}")
                            # 觸發異步刷新快取
                            threading.Thread(target=_flush_checkin_cache, daemon=True).start()
                        else:
                            raise HTTPException(500, f"無法更新子票狀態: {booking_id_from_qr}:{sub_index}")
                    
                    # 母票上車（一次性核銷所有人）
                    elif ticket_type == "mother":
                        checked_count = _checkin_all_sub_tickets(booking_id_from_qr, values, hmap, "check_in_api")
                        log.info(f"[sub_ticket] Checked in all sub-tickets for {booking_id_from_qr}, count={checked_count}")
                        # 觸發異步刷新快取
                        if checked_count > 0:
                            threading.Thread(target=_flush_checkin_cache, daemon=True).start()
                    
                    # 同步狀態到 Sheet
                    _sync_mother_ticket_status_to_sheet(booking_id_from_qr, ws_main, hmap, rowno, values)
                    
                    # 更新最後操作時間
                    if "最後操作時間" in hmap:
                        ws_main.update_cell(rowno, hmap["最後操作時間"], _tz_now_str() + " 已上車")
                    
                    _invalidate_sheet_cache()
                    return {"status": "success", "row": rowno, "booking_id": booking_id_from_qr}
            
            # ========== 向後兼容：舊格式 QR Code ==========
            rownos = _find_rows_by_pred(ws_main, headers, HEADER_ROW_MAIN, lambda r: r.get("QRCode編碼") == p.code or r.get("預約編號") == p.booking_id)
            if not rownos:
                raise HTTPException(404, "找不到符合條件之訂單")
            rowno = rownos[0]
            updates: Dict[str, str] = {}
            if "乘車狀態" in hmap:
                updates["乘車狀態"] = "已上車"
            if "最後操作時間" in hmap:
                updates["最後操作時間"] = _tz_now_str() + " 已上車"
            batch_updates = []
            for col_name, value in updates.items():
                if col_name in hmap:
                    batch_updates.append({"range": gspread.utils.rowcol_to_a1(rowno, hmap[col_name]), "values": [[value]]})
            if batch_updates:
                ws_main.batch_update(batch_updates, value_input_option="USER_ENTERED")
            log.info(f"check_in row={rowno}")
            _invalidate_sheet_cache()
            return {"status": "success", "row": rowno}

        elif action == "split_ticket":
            p = SplitTicketPayload(**data)
            rownos = _find_rows_by_pred(ws_main, headers, HEADER_ROW_MAIN, lambda r: r.get("預約編號") == p.booking_id)
            if not rownos:
                raise HTTPException(404, "找不到此預約編號")
            rowno = rownos[0]
            
            # 獲取總人數和 email
            total_pax = int(get_by_rowno(rowno, "預約人數") or get_by_rowno(rowno, "確認人數") or "0")
            email = get_by_rowno(rowno, "信箱")
            if not email:
                raise HTTPException(400, "此訂單缺少信箱信息，無法分票")
            
            # 檢查是否已經分票
            existing_sub_tickets = _get_sub_tickets_from_sheet(p.booking_id, values, hmap)
            is_re_split = len(existing_sub_tickets) > 0
            
            try:
                if is_re_split:
                    # 重新分票邏輯
                    checked_in_tickets = [t for t in existing_sub_tickets if t.get("status") == "checked_in"]
                    checked_in_pax = sum(t.get("sub_ticket_pax", 0) for t in checked_in_tickets)
                    remaining_pax = total_pax - checked_in_pax
                    
                    if remaining_pax <= 0:
                        raise HTTPException(400, "所有人已上車，無法重新分票")
                    
                    # 重新分票邏輯
                    if sum(p.ticket_split) != remaining_pax:
                        raise HTTPException(400, f"新分票總和 ({sum(p.ticket_split)}) 必須等於剩餘人數 ({remaining_pax})")
                    
                    # 重新分票：保留已上車的子票，為剩餘人數創建新子票
                    new_sub_tickets, _, _ = _re_split_tickets(p.booking_id, p.ticket_split, email, values, hmap)
                    log.info(f"[split_ticket] Re-split booking {p.booking_id}: {checked_in_pax} checked in, {remaining_pax} remaining")
                    
                    # 更新 QRCode編碼（JSON 格式，包含所有子票）
                    # 保留已上車的子票，添加新子票
                    import json
                    qr_dict = {}
                    
                    # 先添加已上車的子票
                    for t in checked_in_tickets:
                        sub_index = t.get("sub_ticket_index")
                        qr_content = t.get("qr_content", "")
                        status = t.get("status", "not_checked_in")
                        pax = t.get("sub_ticket_pax", 0)
                        checked_at = t.get("checked_at")
                        
                        if sub_index and qr_content:
                            qr_dict[str(sub_index)] = {
                                "qr": qr_content,
                                "status": status,
                                "pax": pax,
                                "checked_at": checked_at
                            }
                    
                    # 再添加新子票
                    for t in new_sub_tickets:
                        sub_index = t.get("sub_index")
                        qr_content = t.get("qr_content", "")
                        if sub_index and qr_content:
                            qr_dict[str(sub_index)] = {
                                "qr": qr_content,
                                "status": "not_checked_in",
                                "pax": t.get("pax", 0),
                                "checked_at": None
                            }
                    
                    all_sub_tickets_after = checked_in_tickets + [{"sub_ticket_index": t.get("sub_index"), "sub_ticket_pax": t.get("pax", 0), "qr_content": t.get("qr_content", ""), "status": "not_checked_in"} for t in new_sub_tickets]
                    if "QRCode編碼" in hmap and all_sub_tickets_after:
                        import json
                        qr_dict = {}
                        for t in all_sub_tickets_after:
                            sub_index = t.get("sub_ticket_index")
                            qr_content = t.get("qr_content", "")
                            status = t.get("status", "not_checked_in")
                            pax = t.get("sub_ticket_pax", 0)
                            checked_at = t.get("checked_in_at")
                            
                            if sub_index and qr_content:
                                qr_dict[str(sub_index)] = {
                                    "qr": qr_content,
                                    "status": status,
                                    "pax": pax,
                                    "checked_at": checked_at
                                }
                        
                        if qr_dict:
                            qr_json_str = json.dumps(qr_dict, ensure_ascii=False)
                            ws_main.update_cell(rowno, hmap["QRCode編碼"], qr_json_str)
                else:
                    # 首次分票：只創建子票，不創建母票
                    if sum(p.ticket_split) != total_pax:
                        raise HTTPException(400, f"分票總和 ({sum(p.ticket_split)}) 必須等於總人數 ({total_pax})")
                    
                    sub_tickets = _create_sub_tickets(p.booking_id, p.ticket_split, email)
                    
                    # 更新 Sheet 的 QRCode編碼（JSON 格式）
                    if "QRCode編碼" in hmap and sub_tickets:
                        import json
                        qr_dict = {}
                        
                        for t in sub_tickets:
                            sub_index = t.get("sub_index")
                            qr_content = t.get("qr_content", "")
                            if sub_index and qr_content:
                                qr_dict[str(sub_index)] = {
                                    "qr": qr_content,
                                    "status": "not_checked_in",
                                    "pax": t.get("pax", 0),
                                    "checked_at": None
                                }
                        
                        if qr_dict:
                            qr_json_str = json.dumps(qr_dict, ensure_ascii=False)
                            ws_main.update_cell(rowno, hmap["QRCode編碼"], qr_json_str)
                    
                    log.info(f"[split_ticket] First split booking {p.booking_id} into {len(sub_tickets)} sub-tickets (no mother ticket)")
                    new_sub_tickets = sub_tickets
                
                _invalidate_sheet_cache()
                
                # 返回結果
                def get_suffix_for_split(index: int) -> str:
                    # 子票從 A 開始（A=65, B=66, C=67...）
                    return chr(64 + index) if index <= 26 else f"_{index}"
                
                # 重新分票後，已核銷的票保持不變，新票從下一個索引開始
                
                # 返回所有子票信息（包括已上車的舊子票和新子票）
                all_sub_tickets = _get_sub_tickets_from_sheet(p.booking_id, values, hmap)
                
                # 分票後不返回母票，只返回子票
                return {
                    "status": "success",
                    "booking_id": p.booking_id,
                    "is_re_split": is_re_split,
                    "sub_tickets": [
                        {
                            "sub_index": t.get("sub_ticket_index"),
                            "booking_id": f"{p.booking_id}_{get_suffix_for_split(t.get('sub_ticket_index', 1))}",
                            "pax": t.get("sub_ticket_pax", 0),
                            "status": t.get("status", "not_checked_in"),
                            "qr_content": t.get("qr_content", ""),
                            "qr_url": f"{BASE_URL}/api/qr/{urllib.parse.quote(t.get('qr_content', ''))}"
                        }
                        for t in all_sub_tickets
                    ],
                    "mother_ticket": None  # 分票後不返回母票
                }
            except ValueError as e:
                raise HTTPException(400, str(e))
            except Exception as e:
                log.error(f"[split_ticket] Failed to split ticket: {e}")
                raise HTTPException(500, f"分票失敗: {str(e)}")

        elif action == "mail":
            p = MailPayload(**data)
            rownos = _find_rows_by_pred(ws_main, headers, HEADER_ROW_MAIN, lambda r: r.get("預約編號") == p.booking_id)
            if not rownos:
                raise HTTPException(404, "找不到此預約編號")
            rowno = rownos[0]
            get = lambda k: get_by_rowno(rowno, k)
            info = {"booking_id": get("預約編號"), "date": get("日期"), "time": _time_hm_from_any(get("班次")), "direction": get("往返"), "pick": get("上車地點"), "drop": get("下車地點"), "name": get("姓名"), "phone": get("手機"), "email": get("信箱"), "pax": (get("確認人數") or get("預約人數") or "1")}
            subject, text_body = _compose_mail_text(info, p.lang, p.kind)
            attachment_bytes: Optional[bytes] = None
            if p.kind in ("book", "modify") and p.ticket_png_base64:
                b64 = p.ticket_png_base64
                if b64 and isinstance(b64, str) and "," in b64:
                    b64 = b64.split(",", 1)[1]
                try:
                    if b64:
                        attachment_bytes = base64.b64decode(b64, validate=True)
                except Exception:
                    attachment_bytes = None
            try:
                _send_email_gmail(info["email"], subject, text_body, attachment=attachment_bytes, attachment_filename=f"shuttle_ticket_{info['booking_id']}.png" if attachment_bytes else None)
                status_text = f"{_tz_now_str()} 寄信成功"
            except Exception as e:
                status_text = f"{_tz_now_str()} 寄信失敗: {str(e)}"
            if "寄信狀態" in hmap:
                ws_main.update_acell(gspread.utils.rowcol_to_a1(rowno, hmap["寄信狀態"]), status_text)
            log.info(f"manual mail result: {status_text}")
            return {"status": "success" if "成功" in status_text else "mail_failed", "booking_id": p.booking_id, "mail_note": status_text}
        else:
            raise HTTPException(400, f"未知 action：{action}")
    except HTTPException:
        raise
    except Exception as e:
        log.exception("server error")
        raise HTTPException(500, f"伺服器錯誤: {str(e)}")

@app.get("/api/qr/{code}")
def qr_image(code: str):
    try:
        decoded_code = urllib.parse.unquote(code)
        img = qrcode.make(decoded_code)
        bio = io.BytesIO()
        img.save(bio, format="PNG")
        return Response(content=bio.getvalue(), media_type="image/png")
    except Exception as e:
        raise HTTPException(500, f"QR 生成失敗: {str(e)}")

@app.get("/cors_debug")
def cors_debug():
    return {"status": "ok", "cors_test": True, "time": _tz_now_str()}

@app.get("/api/debug")
def debug_endpoint():
    return {"status": "服務正常", "base_url": BASE_URL, "time": _tz_now_str()}

# ========== 司機數據處理函數 ==========
def build_all_driver_data_optimized(values: List[List[str]], hmap: Dict[str, int]) -> Tuple[List[DriverTrip], List[DriverPassenger], List[DriverAllPassenger]]:
    idx_main_dt = _col_index(hmap, "主班次時間")
    if idx_main_dt < 0:
        return [], [], []
    idx_booking = _col_index(hmap, "預約編號")
    idx_name = _col_index(hmap, "姓名")
    idx_phone = _col_index(hmap, "手機")
    idx_room = _col_index(hmap, "房號")
    idx_pick = _col_index(hmap, "上車地點")
    idx_drop = _col_index(hmap, "下車地點")
    idx_status = _col_index(hmap, "乘車狀態")
    idx_dir = _col_index(hmap, "往返")
    idx_qr = _col_index(hmap, "QRCode編碼")
    idx_confirm_status = _col_index(hmap, "確認狀態")
    idx_rid = _col_index(hmap, "預約編號")
    idx_car_raw = _col_index(hmap, "車次")
    idx_ride = _col_index(hmap, "乘車狀態")
    pax_col = hmap.get("確認人數", hmap.get("預約人數", 0))
    idx_pax = pax_col - 1 if pax_col else -1
    status_col = hmap.get("確認狀態")
    idx_status_check = status_col - 1 if status_col else -1
    STATION_NAMES = {"hotel": "福泰大飯店 Forte Hotel", "mrt": "南港展覽館捷運站 Nangang Exhibition Center - MRT Exit 3", "train": "南港火車站 Nangang Train Station", "mall": "LaLaport Shopping Park"}
    hotel = STATION_NAMES["hotel"]
    mrt = STATION_NAMES["mrt"]
    train = STATION_NAMES["train"]
    mall = STATION_NAMES["mall"]
    SORT_GO_MAP = {hotel: 1, mrt: 2, train: 3, mall: 4}
    SORT_BACK_MAP = {mrt: 1, train: 2, mall: 3}
    DROPOFF_GO_MAP = {mrt: 1, train: 2, mall: 3}
    DROPOFF_BACK_MAP = {mall: 1, train: 2, mrt: 3}
    now = _tz_now()
    cutoff = now - timedelta(hours=1)
    trips_by_dt: Dict[str, DriverTrip] = {}
    trip_passengers_list: List[DriverPassenger] = []
    all_passengers_base: List[Dict[str, Any]] = []
    for row in values[HEADER_ROW_MAIN:]:
        if not any(row):
            continue
        if idx_main_dt >= len(row):
            continue
        main_raw = _get_cell(row, idx_main_dt)
        if not main_raw:
            continue
        if idx_status_check >= 0 and idx_status_check < len(row):
            st = _get_cell(row, idx_status_check)
            if "❌" in st or st == CANCELLED_TEXT:
                continue
        dt = _parse_main_dt(main_raw)
        if not dt:
            continue
        if dt < cutoff:
            continue
        normalized_trip_id = _normalize_main_dt_format(main_raw)
        date_str = dt.strftime("%Y-%m-%d")
        time_str = dt.strftime("%H:%M")
        if normalized_trip_id not in trips_by_dt:
            trips_by_dt[normalized_trip_id] = DriverTrip(trip_id=normalized_trip_id, date=date_str, time=time_str, total_pax=0)
        if idx_pax >= 0 and idx_pax < len(row):
            trips_by_dt[normalized_trip_id].total_pax += _safe_int(row[idx_pax], 0)
        booking_id = _get_cell(row, idx_booking)
        name = _get_cell(row, idx_name)
        phone = _get_cell(row, idx_phone)
        room = _get_cell(row, idx_room) or "(餐客)"
        ride_status = _get_cell(row, idx_status)
        qrcode = _get_cell(row, idx_qr)
        direction = _get_cell(row, idx_dir)
        pick = _get_cell(row, idx_pick)
        drop = _get_cell(row, idx_drop)
        pax = 1
        if idx_pax >= 0 and idx_pax < len(row):
            pax = _safe_int(row[idx_pax], 1)
        if pick:
            trip_passengers_list.append(DriverPassenger(trip_id=normalized_trip_id, station=pick, updown="上車", booking_id=booking_id, name=name, phone=phone, room=room, pax=pax, status=ride_status, direction=direction, qrcode=qrcode))
        if drop:
            trip_passengers_list.append(DriverPassenger(trip_id=normalized_trip_id, station=drop, updown="下車", booking_id=booking_id, name=name, phone=phone, room=room, pax=pax, status=ride_status, direction=direction, qrcode=qrcode))
        rid = _get_cell(row, idx_rid)
        car_raw = _get_cell(row, idx_car_raw)
        phone_raw = _get_cell(row, idx_phone)
        room_raw = _get_cell(row, idx_room)
        qty_raw = _get_cell(row, idx_pax) if idx_pax >= 0 and idx_pax < len(row) else ""
        ride_status_all = _get_cell(row, idx_ride)
        phone_text = phone_raw if phone_raw else ""
        room_text = room_raw if room_raw else ""
        qty = _safe_int(qty_raw, 1)
        up = pick
        down = drop
        sort_go = SORT_GO_MAP.get(up, 99)
        if up in SORT_BACK_MAP:
            sort_back = SORT_BACK_MAP[up]
        elif down == hotel:
            sort_back = 4
        else:
            sort_back = 99
        station_sort = sort_go if direction == "去程" else sort_back
        hotel_go = "上" if (direction == "去程" and up == hotel) else ""
        if up == mrt or down == mrt:
            mrt_col = "上" if up == mrt else "下"
        else:
            mrt_col = ""
        if up == train or down == train:
            train_col = "上" if up == train else "下"
        else:
            train_col = ""
        if up == mall or down == mall:
            mall_col = "上" if up == mall else "下"
        else:
            mall_col = ""
        hotel_back = "下" if (direction == "回程" and down == hotel) else ""
        if direction == "去程":
            dropoff_order = DROPOFF_GO_MAP.get(down, 4)
        elif direction == "回程":
            dropoff_order = DROPOFF_BACK_MAP.get(up, 4)
        else:
            dropoff_order = 99
        all_passengers_base.append(dict(car_raw=car_raw, main_dt_raw=main_raw, main_dt=dt, booking_id=rid, ride_status=ride_status_all, direction=direction, station_sort=station_sort, dropoff_order=dropoff_order, name=name, phone=phone_text, room=room_text, qty=qty, hotel_go=hotel_go, mrt=mrt_col, train=train_col, mall=mall_col, hotel_back=hotel_back))
    trips = sorted(trips_by_dt.values(), key=lambda t: (t.date, t.time))
    def sort_key_passenger(p: DriverPassenger):
        return (p.station, 0 if p.updown == "上車" else 1, p.booking_id)
    trip_passengers = sorted(trip_passengers_list, key=sort_key_passenger)
    def sort_key_all(row: Dict[str, Any]):
        dir_val = row["direction"] or ""
        dir_rank = 0 if dir_val == "去程" else 1
        return (row["main_dt"], dir_rank, row["station_sort"], row["dropoff_order"])
    all_passengers_base.sort(key=sort_key_all)
    result_all: List[DriverAllPassenger] = []
    for row in all_passengers_base:
        dt = row["main_dt"]
        depart_time = dt.strftime("%H:%M") if dt else ""
        normalized_main_dt = _normalize_main_dt_format(row["main_dt_raw"])
        result_all.append(DriverAllPassenger(booking_id=row["booking_id"], main_datetime=normalized_main_dt, depart_time=depart_time, name=row["name"], phone=row["phone"], room=row["room"], pax=row["qty"], ride_status=row["ride_status"], direction=row["direction"], hotel_go=row["hotel_go"], mrt=row["mrt"], train=row["train"], mall=row["mall"], hotel_back=row["hotel_back"]))
    return trips, trip_passengers, result_all

def build_driver_trips(values: List[List[str]], hmap: Dict[str, int]) -> List[DriverTrip]:
    idx_main_dt = _col_index(hmap, "主班次時間")
    if idx_main_dt < 0:
        return []
    pax_col = hmap.get("確認人數", hmap.get("預約人數", 0))
    idx_pax = pax_col - 1 if pax_col else -1
    status_col = hmap.get("確認狀態")
    idx_status = status_col - 1 if status_col else -1
    now = _tz_now()
    cutoff = now - timedelta(hours=1)
    trips_by_dt: Dict[str, DriverTrip] = {}
    for row in values[HEADER_ROW_MAIN:]:
        if not any(row):
            continue
        if idx_main_dt >= len(row):
            continue
        main_raw = _get_cell(row, idx_main_dt)
        if not main_raw:
            continue
        if idx_status >= 0 and idx_status < len(row):
            st = _get_cell(row, idx_status)
            if "❌" in st or st == CANCELLED_TEXT:
                continue
        dt = _parse_main_dt(main_raw)
        if not dt:
            continue
        if dt < cutoff:
            continue
        date_str = dt.strftime("%Y-%m-%d")
        time_str = dt.strftime("%H:%M")
        normalized_trip_id = _normalize_main_dt_format(main_raw)
        if normalized_trip_id not in trips_by_dt:
            trips_by_dt[normalized_trip_id] = DriverTrip(trip_id=normalized_trip_id, date=date_str, time=time_str, total_pax=0)
        if idx_pax >= 0 and idx_pax < len(row):
            normalized_trip_id = _normalize_main_dt_format(main_raw)
            trips_by_dt[normalized_trip_id].total_pax += _safe_int(row[idx_pax], 0)
    return sorted(trips_by_dt.values(), key=lambda t: (t.date, t.time))

def build_driver_trip_passengers(values: List[List[str]], hmap: Dict[str, int], trip_id: Optional[str] = None) -> List[DriverPassenger]:
    idx_main_dt = _col_index(hmap, "主班次時間")
    if idx_main_dt < 0:
        return []
    idx_booking = _col_index(hmap, "預約編號")
    idx_name = _col_index(hmap, "姓名")
    idx_phone = _col_index(hmap, "手機")
    idx_room = _col_index(hmap, "房號")
    pax_col = hmap.get("確認人數", hmap.get("預約人數", 0))
    idx_pax = pax_col - 1 if pax_col else -1
    idx_pick = _col_index(hmap, "上車地點")
    idx_drop = _col_index(hmap, "下車地點")
    idx_status = _col_index(hmap, "乘車狀態")
    idx_dir = _col_index(hmap, "往返")
    idx_qr = _col_index(hmap, "QRCode編碼")
    idx_confirm_status = _col_index(hmap, "確認狀態")
    result: List[DriverPassenger] = []
    for row in values[HEADER_ROW_MAIN:]:
        if not any(row):
            continue
        if idx_main_dt >= len(row):
            continue
        main_raw = _get_cell(row, idx_main_dt)
        if not main_raw:
            continue
        if idx_confirm_status >= 0 and idx_confirm_status < len(row):
            confirm_status = _get_cell(row, idx_confirm_status)
            if "❌" in confirm_status or confirm_status == CANCELLED_TEXT:
                continue
        if trip_id is not None and main_raw != trip_id:
            continue
        booking_id = _get_cell(row, idx_booking)
        name = _get_cell(row, idx_name)
        phone = _get_cell(row, idx_phone)
        room = _get_cell(row, idx_room) or "(餐客)"
        ride_status = _get_cell(row, idx_status)
        qrcode = _get_cell(row, idx_qr)
        direction = _get_cell(row, idx_dir)
        pax = 1
        if idx_pax >= 0 and idx_pax < len(row):
            pax = _safe_int(row[idx_pax], 1)
        pick = _get_cell(row, idx_pick)
        drop = _get_cell(row, idx_drop)
        normalized_trip_id = _normalize_main_dt_format(main_raw)
        if pick:
            result.append(DriverPassenger(trip_id=normalized_trip_id, station=pick, updown="上車", booking_id=booking_id, name=name, phone=phone, room=room, pax=pax, status=ride_status, direction=direction, qrcode=qrcode))
        if drop:
            result.append(DriverPassenger(trip_id=normalized_trip_id, station=drop, updown="下車", booking_id=booking_id, name=name, phone=phone, room=room, pax=pax, status=ride_status, direction=direction, qrcode=qrcode))
    def sort_key(p: DriverPassenger):
        return (p.station, 0 if p.updown == "上車" else 1, p.booking_id)
    return sorted(result, key=sort_key)

def build_driver_all_passengers(values: List[List[str]], hmap: Dict[str, int]) -> List[DriverAllPassenger]:
    def col_idx(name: str) -> int:
        return _col_index(hmap, name)
    idx_rid = col_idx("預約編號")
    idx_car_raw = col_idx("車次")
    idx_main_dt = col_idx("主班次時間")
    idx_dir = col_idx("往返")
    idx_up = col_idx("上車地點")
    idx_down = col_idx("下車地點")
    idx_name = col_idx("姓名")
    idx_phone = col_idx("手機")
    idx_room = col_idx("房號")
    idx_qty = col_idx("確認人數")
    idx_status = col_idx("確認狀態")
    idx_ride = col_idx("乘車狀態")
    if idx_main_dt < 0:
        return []
    STATION_NAMES = {"hotel": "福泰大飯店 Forte Hotel", "mrt": "南港展覽館捷運站 Nangang Exhibition Center - MRT Exit 3", "train": "南港火車站 Nangang Train Station", "mall": "LaLaport Shopping Park"}
    hotel = STATION_NAMES["hotel"]
    mrt = STATION_NAMES["mrt"]
    train = STATION_NAMES["train"]
    mall = STATION_NAMES["mall"]
    now = _tz_now()
    cutoff = now - timedelta(hours=1)
    SORT_GO_MAP = {hotel: 1, mrt: 2, train: 3, mall: 4}
    SORT_BACK_MAP = {mrt: 1, train: 2, mall: 3}
    DROPOFF_GO_MAP = {mrt: 1, train: 2, mall: 3}
    DROPOFF_BACK_MAP = {mall: 1, train: 2, mrt: 3}
    base_rows: List[Dict[str, Any]] = []
    for row in values[HEADER_ROW_MAIN:]:
        if not any(row):
            continue
        if idx_main_dt >= len(row):
            continue
        main_raw = _get_cell(row, idx_main_dt)
        if not main_raw:
            continue
        dt = _parse_main_dt(main_raw)
        if not dt:
            continue
        if dt < cutoff:
            continue
        status_val = _get_cell(row, idx_status)
        if "❌" in status_val:
            continue
        rid = _get_cell(row, idx_rid)
        car_raw = _get_cell(row, idx_car_raw)
        direction = _get_cell(row, idx_dir)
        up = _get_cell(row, idx_up)
        down = _get_cell(row, idx_down)
        name = _get_cell(row, idx_name)
        phone_raw = _get_cell(row, idx_phone)
        room_raw = _get_cell(row, idx_room)
        qty_raw = _get_cell(row, idx_qty)
        ride_status = _get_cell(row, idx_ride)
        phone_text = phone_raw if phone_raw else ""
        room_text = room_raw if room_raw else ""
        qty = _safe_int(qty_raw, 1)
        sort_go = SORT_GO_MAP.get(up, 99)
        if up in SORT_BACK_MAP:
            sort_back = SORT_BACK_MAP[up]
        elif down == hotel:
            sort_back = 4
        else:
            sort_back = 99
        station_sort = sort_go if direction == "去程" else sort_back
        hotel_go = "上" if (direction == "去程" and up == hotel) else ""
        if up == mrt or down == mrt:
            mrt_col = "上" if up == mrt else "下"
        else:
            mrt_col = ""
        if up == train or down == train:
            train_col = "上" if up == train else "下"
        else:
            train_col = ""
        if up == mall or down == mall:
            mall_col = "上" if up == mall else "下"
        else:
            mall_col = ""
        hotel_back = "下" if (direction == "回程" and down == hotel) else ""
        if direction == "去程":
            dropoff_order = DROPOFF_GO_MAP.get(down, 4)
        elif direction == "回程":
            dropoff_order = DROPOFF_BACK_MAP.get(up, 4)
        else:
            dropoff_order = 99
        base_rows.append(dict(car_raw=car_raw, main_dt_raw=main_raw, main_dt=dt, booking_id=rid, ride_status=ride_status, direction=direction, station_sort=station_sort, dropoff_order=dropoff_order, name=name, phone=phone_text, room=room_text, qty=qty, hotel_go=hotel_go, mrt=mrt_col, train=train_col, mall=mall_col, hotel_back=hotel_back))
    def sort_key(row: Dict[str, Any]):
        dir_val = row["direction"] or ""
        dir_rank = 0 if dir_val == "去程" else 1
        return (row["main_dt"], dir_rank, row["station_sort"], row["dropoff_order"])
    base_rows.sort(key=sort_key)
    result: List[DriverAllPassenger] = []
    for row in base_rows:
        dt = row["main_dt"]
        depart_time = dt.strftime("%H:%M") if dt else ""
        normalized_main_dt = _normalize_main_dt_format(row["main_dt_raw"])
        result.append(DriverAllPassenger(booking_id=row["booking_id"], main_datetime=normalized_main_dt, depart_time=depart_time, name=row["name"], phone=row["phone"], room=row["room"], pax=row["qty"], ride_status=row["ride_status"], direction=row["direction"], hotel_go=row["hotel_go"], mrt=row["mrt"], train=row["train"], mall=row["mall"], hotel_back=row["hotel_back"]))
    return result

# ========== 站點到達檢測 ==========
def check_station_arrival(lat: float, lng: float, trip_id: str):
    if not firebase_admin._apps:
        return
    try:
        root_ref = db.reference("/")
        firebase_data = root_ref.get()
        if not firebase_data:
            return
        stations_info = firebase_data.get("current_trip_stations", {})
        if not stations_info or "stops" not in stations_info:
            return
        actual_stops_names = stations_info.get("stops", [])
        if not actual_stops_names:
            return
        completed_stops = firebase_data.get("current_trip_completed_stops", [])
        route_data = firebase_data.get("current_trip_route", {})
        route_path = route_data.get("path", []) if route_data else []
        completed_stops_ref = db.reference("/current_trip_completed_stops")
        def get_station_threshold(stop_name: str) -> float:
            if "飯店" in stop_name or "Hotel" in stop_name:
                return 60
            elif "捷運" in stop_name or "MRT" in stop_name:
                return 40
            elif "火車" in stop_name or "Train" in stop_name:
                return 40
            else:
                return 50
        for stop_name in actual_stops_names:
            if stop_name in completed_stops:
                continue
            stop_coord = STATION_COORDS.get(stop_name)
            if not stop_coord:
                continue
            stop_lat = stop_coord["lat"]
            stop_lng = stop_coord["lng"]
            distance = haversine_distance(lat, lng, stop_lat, stop_lng)
            threshold = get_station_threshold(stop_name)
            distance_check = distance < threshold
            route_index_check = False
            if route_path and len(route_path) > 0:
                station_nearest_idx = 0
                station_best_dist = float('inf')
                for i, point in enumerate(route_path):
                    dx = point.get("lat", 0) - stop_lat
                    dy = point.get("lng", 0) - stop_lng
                    dist = dx * dx + dy * dy
                    if dist < station_best_dist:
                        station_best_dist = dist
                        station_nearest_idx = i
                driver_nearest_idx = 0
                driver_best_dist = float('inf')
                for i, point in enumerate(route_path):
                    dx = point.get("lat", 0) - lat
                    dy = point.get("lng", 0) - lng
                    dist = dx * dx + dy * dy
                    if dist < driver_best_dist:
                        driver_best_dist = dist
                        driver_nearest_idx = i
                if driver_nearest_idx > station_nearest_idx and distance < 100:
                    route_index_check = True
            if distance_check or route_index_check:
                if stop_name not in completed_stops:
                    completed_stops.append(stop_name)
                    completed_stops_ref.set(completed_stops)
                    next_stop = get_next_station(actual_stops_names, completed_stops)
                    if next_stop:
                        db.reference("/current_trip_station").set(next_stop)
                    else:
                        db.reference("/current_trip_station").set("所有站點已完成")
                break
    except Exception as e:
        log.warning(f"check_station_arrival error: {e}", exc_info=True)

def auto_complete_trip(trip_id: str = None, main_datetime: str = None):
    if not trip_id and not main_datetime:
        return False
    main_dt_str = main_datetime or trip_id
    dt = _parse_main_dt(main_dt_str)
    if dt:
        ws2 = None
        target_rowno: Optional[int] = None
        try:
            try:
                ws2 = open_ws("車次管理(櫃台)")
            except Exception:
                ws2 = open_ws("車次管理(備品)")
            headers = ws2.row_values(6)
            headers = [(h or "").strip() for h in headers]
            def hidx(name: str) -> int:
                try:
                    return headers.index(name)
                except ValueError:
                    return -1
            idx_date = hidx("日期")
            idx_time = hidx("班次") if hidx("時間") < 0 else hidx("時間")
            idx_status = hidx("出車狀態")
            idx_last = hidx("最後更新")
            target_date = dt.strftime("%Y/%m/%d")
            alt_date = dt.strftime("%Y-%m-%d")
            t1 = dt.strftime("%H:%M")
            t2 = dt.strftime("%-H:%M") if hasattr(dt, "strftime") else t1
            values = ws2.get_all_values()
            for i in range(6, len(values)):
                row = values[i]
                d = (row[idx_date] if idx_date >= 0 and idx_date < len(row) else "").strip()
                t_raw = (row[idx_time] if idx_time >= 0 and idx_time < len(row) else "").strip()
                try:
                    rp = t_raw.split(":")
                    t_norm = f"{str(rp[0]).zfill(2)}:{rp[1]}" if len(rp) >= 2 else t_raw
                except Exception:
                    t_norm = t_raw
                if (d in (target_date, alt_date)) and (t_raw in (t1, t2) or t_norm in (t1, t2)):
                    target_rowno = i + 1
                    break
            if target_rowno and idx_status >= 0 and idx_last >= 0:
                now_text = _tz_now().strftime("%Y/%m/%d %H:%M")
                update_data = [{"range": gspread.utils.rowcol_to_a1(target_rowno, idx_status + 1), "values": [["已結束"]]}, {"range": gspread.utils.rowcol_to_a1(target_rowno, idx_last + 1), "values": [[now_text]]}]
                ws2.batch_update(update_data, value_input_option="USER_ENTERED")
                _invalidate_ws_cache("車次管理(櫃台)")
                _invalidate_ws_cache("車次管理(備品)")
        except Exception:
            pass
    try:
        if not firebase_admin._apps:
            service_account_path = "service_account.json"
            if os.path.exists(service_account_path):
                cred = credentials.Certificate(service_account_path)
            else:
                cred = credentials.ApplicationDefault()
            db_url = os.environ.get("FIREBASE_RTDB_URL")
            if not db_url:
                project_id = os.environ.get("GOOGLE_CLOUD_PROJECT", "shuttle-system-487204")
                db_url = f"https://{project_id}-default-rtdb.asia-southeast1.firebasedatabase.app/"
            firebase_admin.initialize_app(cred, {"databaseURL": db_url})
        try:
            path_history_ref = db.reference("/current_trip_path_history")
            path_history_ref.set([])
        except Exception:
            pass
        db.reference("/current_trip_id").set("")
        db.reference("/current_trip_route").set({})
        db.reference("/current_trip_status").set("ended")
        db.reference("/current_trip_path_history").set([])
        try:
            last_trip_datetime = db.reference("/current_trip_datetime").get()
            if last_trip_datetime:
                db.reference("/last_trip_datetime").set(last_trip_datetime)
        except Exception:
            pass
        db.reference("/current_trip_datetime").set("")
        db.reference("/current_trip_stations").set({})
    except Exception:
        pass
    return True

# ========== Driver API2 端點 ==========
@app.post("/api/driver/location")
def update_driver_location(loc: DriverLocation):
    global DRIVER_LOCATION_CACHE
    with LOCATION_LOCK:
        DRIVER_LOCATION_CACHE["lat"] = loc.lat
        DRIVER_LOCATION_CACHE["lng"] = loc.lng
        DRIVER_LOCATION_CACHE["timestamp"] = loc.timestamp
        DRIVER_LOCATION_CACHE["updated_at"] = _tz_now_str()
    try:
        if not firebase_admin._apps:
            service_account_path = "service_account.json"
            if os.path.exists(service_account_path):
                cred = credentials.Certificate(service_account_path)
            else:
                cred = credentials.ApplicationDefault()
            db_url = os.environ.get("FIREBASE_RTDB_URL")
            if not db_url:
                project_id = os.environ.get("GOOGLE_CLOUD_PROJECT", "shuttle-system-487204")
                db_url = f"https://{project_id}-default-rtdb.asia-southeast1.firebasedatabase.app/"
            firebase_admin.initialize_app(cred, {"databaseURL": db_url})
        if firebase_admin._apps:
            ref = db.reference("/driver_location")
            location_data = {"lat": loc.lat, "lng": loc.lng, "timestamp": loc.timestamp, "updated_at": DRIVER_LOCATION_CACHE["updated_at"]}
            if loc.trip_id:
                location_data["trip_id"] = loc.trip_id
            ref.set(location_data)
            if loc.trip_id:
                try:
                    current_trip_id = db.reference("/current_trip_id").get()
                    if current_trip_id == loc.trip_id:
                        path_history_ref = db.reference("/current_trip_path_history")
                        current_history = path_history_ref.get() or []
                        now_ts = int(time.time() * 1000)
                        THIRTY_MINUTES_MS = 60 * 60 * 1000
                        current_history = [point for point in current_history if point.get("timestamp", 0) > (now_ts - THIRTY_MINUTES_MS)]
                        should_record = True
                        if len(current_history) > 0:
                            last_point = current_history[-1]
                            last_ts = last_point.get("timestamp", 0)
                            time_diff = now_ts - last_ts
                            MIN_INTERVAL_MS = 5 * 1000
                            if time_diff < MIN_INTERVAL_MS:
                                should_record = False
                        if should_record:
                            new_point = {"lat": loc.lat, "lng": loc.lng, "timestamp": loc.timestamp, "updated_at": DRIVER_LOCATION_CACHE["updated_at"]}
                            current_history.append(new_point)
                            MAX_HISTORY_POINTS = 500
                            if len(current_history) > MAX_HISTORY_POINTS:
                                current_history = current_history[-MAX_HISTORY_POINTS:]
                            path_history_ref.set(current_history)
                except Exception:
                    pass
            if loc.trip_id:
                try:
                    check_station_arrival(loc.lat, loc.lng, loc.trip_id)
                except Exception:
                    pass
            try:
                trip_status = db.reference("/current_trip_status").get()
                trip_start_time = db.reference("/current_trip_start_time").get()
                trip_datetime = db.reference("/current_trip_datetime").get()
                trip_id_ref = db.reference("/current_trip_id").get()
                if trip_status == "active" and trip_start_time:
                    now_ms = int(time.time() * 1000)
                    elapsed_ms = now_ms - int(trip_start_time)
                    if elapsed_ms >= AUTO_SHUTDOWN_MS:
                        auto_complete_trip(trip_id=trip_id_ref or "", main_datetime=trip_datetime or "")
            except Exception:
                pass
    except Exception as e:
        log.error(f"Unexpected error in update_driver_location: {e}", exc_info=True)
    return {"status": "ok", "received": loc}

@app.get("/api/driver/location")
def get_driver_location():
    try:
        if not firebase_admin._apps:
            service_account_path = "service_account.json"
            if os.path.exists(service_account_path):
                cred = credentials.Certificate(service_account_path)
            else:
                cred = credentials.ApplicationDefault()
            db_url = os.environ.get("FIREBASE_RTDB_URL")
            if not db_url:
                project_id = os.environ.get("GOOGLE_CLOUD_PROJECT", "shuttle-system-487204")
                db_url = f"https://{project_id}-default-rtdb.asia-southeast1.firebasedatabase.app/"
            firebase_admin.initialize_app(cred, {"databaseURL": db_url})
        if firebase_admin._apps:
            ref = db.reference("/driver_location")
            data = ref.get()
            if data:
                return data
            else:
                return {"lat": 0, "lng": 0, "timestamp": 0, "status": "no_data_in_firebase"}
    except Exception as e:
        return {"lat": 0, "lng": 0, "timestamp": 0, "status": "error", "error_detail": str(e), "hint": "Check Cloud Run logs or FIREBASE_RTDB_URL env var."}
    return {"lat": 0, "lng": 0, "timestamp": 0, "status": "firebase_not_initialized"}

@app.get("/api/driver/data", response_model=DriverAllData)
def driver_get_all_data():
    values, hmap = _get_sheet_data_main()
    trips, trip_passengers, passenger_list = build_all_driver_data_optimized(values, hmap)
    return DriverAllData(trips=trips, trip_passengers=trip_passengers, passenger_list=passenger_list)

@app.get("/api/driver/trips", response_model=List[DriverTrip])
def driver_get_trips():
    values, hmap = _get_sheet_data_main()
    return build_driver_trips(values, hmap)

@app.get("/api/driver/trip_passengers", response_model=List[DriverPassenger])
def driver_get_trip_passengers(trip_id: str = Query(..., description="主班次時間原始字串，例如 2025/12/08 18:30")):
    values, hmap = _get_sheet_data_main()
    return build_driver_trip_passengers(values, hmap, trip_id=trip_id)

@app.get("/api/driver/passenger_list", response_model=List[DriverAllPassenger])
def driver_get_passenger_list():
    values, hmap = _get_sheet_data_main()
    return build_driver_all_passengers(values, hmap)

@app.post("/api/driver/checkin", response_model=DriverCheckinResponse)
def api_driver_checkin(req: DriverCheckinRequest):
    code = (req.qrcode or "").strip()
    if not code:
        raise HTTPException(400, "缺少 qrcode")
    
    # 解析 QR Code
    qr_info = _parse_qr_code(code)
    if not qr_info:
        return DriverCheckinResponse(status="error", message="QRCode 格式錯誤")
    
    booking_id = qr_info["booking_id"]
    sub_index = qr_info.get("sub_index", 0)
    
    # 查找 Sheet 中的預約（使用快取）
    values, hmap = _get_sheet_data_main()
    ws = open_ws(SHEET_NAME_MAIN)  # 仍需要 ws 對象用於更新
    if "QRCode編碼" not in hmap:
        raise HTTPException(500, "主表缺少『QRCode編碼』欄位")
    
    # 根據是否為子票選擇查找方式
    rowno = None
    if sub_index > 0:
        # 子票：在 QRCode編碼（JSON）中查找
        rowno = _find_qrcode_row_json(values, hmap, booking_id, sub_index)
    else:
        # 舊格式：在 QRCode編碼（字符串）中查找
        rowno = _find_qrcode_row(values, hmap, code)
    
    if rowno is None:
        return DriverCheckinResponse(status="not_found", message="找不到對應的預約（QRCode編碼）")
    
    row_idx = rowno - 1
    row = values[row_idx] if 0 <= row_idx < len(values) else []
    def getv(col_name: str) -> str:
        ci = hmap.get(col_name, 0) - 1
        if ci < 0 or ci >= len(row):
            return ""
        return row[ci] or ""
    
    sheet_booking_id = getv("預約編號").strip()
    if sheet_booking_id:
        booking_id = sheet_booking_id
    
    main_raw = getv("主班次時間").strip()
    if not main_raw:
        return DriverCheckinResponse(status="error", message="此預約缺少『主班次時間』，無法核銷上車", booking_id=booking_id or None)
    main_dt = _parse_main_dt(main_raw)
    if not main_dt:
        log.warning(f"api_driver_checkin: 無法解析主班次時間: {main_raw}, booking_id: {booking_id}")
        return DriverCheckinResponse(status="error", message=f"主班次時間格式錯誤：{main_raw}", booking_id=booking_id or None)
    
    # 時間範圍檢查
    now = _tz_now()
    diff_sec = (now - main_dt).total_seconds()
    limit_before = 30 * 60
    limit_after = 60 * 60
    if diff_sec > limit_after:
        pax_str = getv("確認人數") or getv("預約人數") or "1"
        pax = _safe_int(pax_str, 1)
        return DriverCheckinResponse(status="expired", message="此班次已逾期，無法核銷上車", booking_id=booking_id or None, name=getv("姓名") or None, pax=pax, station=getv("上車地點") or None, main_datetime=main_dt.strftime("%Y/%m/%d %H:%M"))
    if diff_sec < -limit_before:
        dt_str = main_dt.strftime("%Y/%m/%d %H:%M")
        pax_str = getv("確認人數") or getv("預約人數") or "1"
        pax = _safe_int(pax_str, 1)
        return DriverCheckinResponse(status="not_started", message=f"{dt_str} 班次，尚未發車", booking_id=booking_id or None, name=getv("姓名") or None, pax=pax, station=getv("上車地點") or None, main_datetime=dt_str)
    
    # 處理核銷
    updates: Dict[str, str] = {}
    checked_pax = 0
    total_pax = 0
    ride_status = ""
    sub_ticket_pax = 0
    
    if sub_index > 0:
        # 子票核銷：從 Sheet JSON 讀取子票信息
        sub_tickets = _get_sub_tickets_from_sheet(booking_id, values, hmap)
        target_ticket = None
        for t in sub_tickets:
            if t.get("sub_ticket_index") == sub_index:
                target_ticket = t
                break
        
        if not target_ticket:
            return DriverCheckinResponse(status="not_found", message="找不到對應的子票", booking_id=booking_id or None)
        
        # 檢查是否已核銷（檢查快取和 Sheet）
        global CHECKIN_CACHE, CHECKIN_CACHE_LOCK
        with CHECKIN_CACHE_LOCK:
            cache_data = CHECKIN_CACHE.get(booking_id, {})
            already_checked = sub_index in cache_data or target_ticket.get("status") == "checked_in"
        
        if already_checked:
            # 已核銷，返回當前狀態
            status_text, checked_pax, total_pax = _calculate_mother_ticket_status(booking_id, values, hmap)
            sub_ticket_pax = target_ticket.get("sub_ticket_pax", 0)
            return DriverCheckinResponse(
                status="already_checked_in",
                message="此子票已上車，不重複核銷",
                booking_id=booking_id or None,
                name=getv("姓名") or None,
                pax=sub_ticket_pax,
                station=getv("上車地點") or None,
                main_datetime=main_dt.strftime("%Y/%m/%d %H:%M"),
                sub_index=sub_index,
                checked_pax=checked_pax,
                total_pax=total_pax,
                ride_status=status_text
            )
        
        # 更新到內存快取（批量寫回）
        if not _update_sub_ticket_status_in_cache(booking_id, sub_index, "driver"):
            # 如果已經在快取中，返回已核銷
            status_text, checked_pax, total_pax = _calculate_mother_ticket_status(booking_id, values, hmap)
            sub_ticket_pax = target_ticket.get("sub_ticket_pax", 0)
            return DriverCheckinResponse(
                status="already_checked_in",
                message="此子票已上車，不重複核銷",
                booking_id=booking_id or None,
                name=getv("姓名") or None,
                pax=sub_ticket_pax,
                station=getv("上車地點") or None,
                main_datetime=main_dt.strftime("%Y/%m/%d %H:%M"),
                sub_index=sub_index,
                checked_pax=checked_pax,
                total_pax=total_pax,
                ride_status=status_text
            )
        
        # 計算總狀態（包含快取中的狀態）
        status_text, checked_pax, total_pax = _calculate_mother_ticket_status(booking_id, values, hmap)
        ride_status = status_text
        sub_ticket_pax = target_ticket.get("sub_ticket_pax", 0)
        
        # 觸發異步刷新快取（不阻塞響應）
        threading.Thread(target=_flush_checkin_cache, daemon=True).start()
    else:
        # 舊格式（未分票）：直接更新 Sheet
        ride_status_current = getv("乘車狀態").strip()
        if ride_status_current and ("已上車" in ride_status_current or "上車" in ride_status_current):
            pax_str = getv("確認人數") or getv("預約人數") or "1"
            pax = _safe_int(pax_str, 1)
            return DriverCheckinResponse(status="already_checked_in", message="此乘客已上車，不重複核銷", booking_id=booking_id or None, name=getv("姓名") or None, pax=pax, station=getv("上車地點") or None, main_datetime=main_dt.strftime("%Y/%m/%d %H:%M"))
        
        updates["乘車狀態"] = "已上車"
        if "最後操作時間" in hmap:
            updates["最後操作時間"] = _tz_now_str() + " 已上車(司機)"
        
        pax_str = getv("確認人數") or getv("預約人數") or "1"
        sub_ticket_pax = _safe_int(pax_str, 1)
        total_pax = sub_ticket_pax
        checked_pax = sub_ticket_pax
        ride_status = "已上車"
    
    # 批量更新 Sheet
    if updates:
        data = []
        for col_name, val in updates.items():
            if col_name in hmap:
                ci = hmap[col_name]
                data.append({"range": gspread.utils.rowcol_to_a1(rowno, ci), "values": [[val]]})
        if data:
            ws.batch_update(data, value_input_option="USER_ENTERED")
    
    _invalidate_sheet_cache()
    
    # 返回詳細狀態
    return DriverCheckinResponse(
        status="success",
        message="已完成上車紀錄",
        booking_id=booking_id or None,
        name=getv("姓名") or None,
        pax=sub_ticket_pax if sub_ticket_pax > 0 else (_safe_int(getv("確認人數") or getv("預約人數") or "1", 1)),
        station=getv("上車地點") or None,
        main_datetime=main_dt.strftime("%Y/%m/%d %H:%M"),
        sub_index=sub_index if sub_index > 0 else None,
        checked_pax=checked_pax if checked_pax > 0 else None,
        total_pax=total_pax if total_pax > 0 else None,
        ride_status=ride_status if ride_status else None
    )

@app.post("/api/driver/no_show")
def api_driver_no_show(req: BookingIdRequest):
    values, hmap = _get_sheet_data_main()
    ws = open_ws(SHEET_NAME_MAIN)
    target_rowno = _find_booking_row(values, hmap, req.booking_id)
    if not target_rowno:
        raise HTTPException(status_code=404, detail="找不到對應預約編號")
    data = []
    if "乘車狀態" in hmap:
        data.append({"range": gspread.utils.rowcol_to_a1(target_rowno, hmap["乘車狀態"]), "values": [["No-show"]]})
    if "最後操作時間" in hmap:
        data.append({"range": gspread.utils.rowcol_to_a1(target_rowno, hmap["最後操作時間"]), "values": [[_tz_now_str() + " No-show(司機)"]]})
    if data:
        ws.batch_update(data, value_input_option="USER_ENTERED")
    _invalidate_sheet_cache()
    return {"status": "success"}

@app.post("/api/driver/manual_boarding")
def api_driver_manual_boarding(req: BookingIdRequest):
    values, hmap = _get_sheet_data_main()
    ws = open_ws(SHEET_NAME_MAIN)
    target_rowno = _find_booking_row(values, hmap, req.booking_id)
    if not target_rowno:
        raise HTTPException(status_code=404, detail="找不到對應預約編號")
    data = []
    if "乘車狀態" in hmap:
        data.append({"range": gspread.utils.rowcol_to_a1(target_rowno, hmap["乘車狀態"]), "values": [["已上車"]]})
    if "最後操作時間" in hmap:
        data.append({"range": gspread.utils.rowcol_to_a1(target_rowno, hmap["最後操作時間"]), "values": [[_tz_now_str() + " 人工驗票(司機)"]]})
    if data:
        ws.batch_update(data, value_input_option="USER_ENTERED")
    _invalidate_sheet_cache()
    return {"status": "success"}

@app.post("/api/driver/trip_status")
def api_driver_trip_status(req: TripStatusRequest):
    sheet_name = "車次管理(櫃台)"
    try:
        ws = open_ws(sheet_name)
    except (gspread.exceptions.SpreadsheetNotFound, gspread.exceptions.WorksheetNotFound):
        ws = open_ws("車次管理(備品)")
    except Exception:
        ws = open_ws("車次管理(備品)")
    headers = ws.row_values(6)
    headers = [(h or "").strip() for h in headers]
    def hidx(name: str) -> int:
        try:
            return headers.index(name)
        except ValueError:
            return -1
    idx_date = hidx("日期")
    idx_time = hidx("時間")
    if idx_time < 0:
        idx_time = hidx("班次")
    idx_status = hidx("出車狀態")
    idx_last = hidx("最後更新")
    if min(idx_date, idx_time, idx_status, idx_last) < 0:
        raise HTTPException(status_code=400, detail="表頭缺少必要欄位")
    raw = req.main_datetime.strip()
    parts = raw.split(" ")
    if len(parts) < 2:
        raise HTTPException(status_code=400, detail="主班次時間格式錯誤")
    target_date, target_time = parts[0], parts[1]
    def norm_dates(d: str) -> list:
        d = d.strip()
        if "-" in d:
            y, m, day = d.split("-")
        else:
            y, m, day = d.split("/")
        m2 = str(m).zfill(2)
        d2 = str(day).zfill(2)
        return [f"{y}/{m2}/{d2}", f"{y}-{m2}-{d2}"]
    def norm_time(t: str) -> list:
        t = t.strip()
        parts = t.split(":")
        if len(parts) == 1:
            return [t]
        h = parts[0]
        mm = parts[1] if len(parts) > 1 else "00"
        ss = parts[2] if len(parts) > 2 else None
        h2 = str(h).zfill(2)
        res = [f"{h2}:{mm}", f"{int(h)}:{mm}"]
        if ss is not None:
            res.append(f"{h2}:{mm}:{ss}")
            res.append(f"{int(h)}:{mm}:{ss}")
        return res
    t_dates = norm_dates(target_date)
    t_times = norm_time(target_time)
    values = ws.get_all_values()
    target_rowno: Optional[int] = None
    for i in range(6, len(values)):
        row = values[i]
        d = (row[idx_date] if idx_date < len(row) else "").strip()
        t_raw = (row[idx_time] if idx_time < len(row) else "").strip()
        try:
            rp = t_raw.split(":")
            t_norm = f"{str(rp[0]).zfill(2)}:{rp[1]}" if len(rp) >= 2 else t_raw
        except Exception:
            t_norm = t_raw
        if (d in t_dates) and (t_raw in t_times or t_norm in t_times):
            target_rowno = i + 1
            break
    if not target_rowno:
        raise HTTPException(status_code=404, detail="找不到對應主班次時間")
    now_text = _tz_now().strftime("%Y/%m/%d %H:%M")
    data = [{"range": gspread.utils.rowcol_to_a1(target_rowno, idx_status + 1), "values": [[req.status]]}, {"range": gspread.utils.rowcol_to_a1(target_rowno, idx_last + 1), "values": [[now_text]]}]
    ws.batch_update(data, value_input_option="USER_ENTERED")
    _invalidate_ws_cache("車次管理(櫃台)")
    _invalidate_ws_cache("車次管理(備品)")
    return {"status": "success"}

@app.post("/api/driver/qrcode_info", response_model=QrInfoResponse)
def api_driver_qrinfo(req: QrInfoRequest):
    values, hmap = _get_sheet_data_main()
    rowno = _find_qrcode_row(values, hmap, req.qrcode)
    if not rowno:
        return QrInfoResponse(booking_id=None, name=None, main_datetime=None, ride_status=None, station_up=None, station_down=None)
    row = values[rowno-1]
    def getv(col: str) -> str:
        ci = hmap.get(col, 0)-1
        return (row[ci] if 0 <= ci < len(row) else "").strip()
    main_raw = getv("主班次時間")
    return QrInfoResponse(booking_id=getv("預約編號") or None, name=getv("姓名") or None, main_datetime=main_raw or None, ride_status=getv("乘車狀態") or None, station_up=getv("上車地點") or None, station_down=getv("下車地點") or None)

@app.post("/api/driver/google/trip_start", response_model=GoogleTripStartResponse)
def api_driver_google_trip_start(req: GoogleTripStartRequest):
    dt = _parse_main_dt(req.main_datetime)
    if not dt:
        raise HTTPException(status_code=400, detail="主班次時間格式錯誤")
    trip_id = dt.strftime("%Y/%m/%d %H:%M")
    ws2 = None
    target_rowno: Optional[int] = None
    try:
        try:
            ws2 = open_ws("車次管理(櫃台)")
        except Exception:
            ws2 = open_ws("車次管理(備品)")
        headers = ws2.row_values(6)
        headers = [(h or "").strip() for h in headers]
        def hidx(name: str) -> int:
            try:
                return headers.index(name)
            except ValueError:
                return -1
        idx_date = hidx("日期")
        idx_time = hidx("班次") if hidx("時間") < 0 else hidx("時間")
        idx_status = hidx("出車狀態")
        idx_last = hidx("最後更新")
        target_date = dt.strftime("%Y/%m/%d")
        alt_date = dt.strftime("%Y-%m-%d")
        t1 = dt.strftime("%H:%M")
        t2 = dt.strftime("%-H:%M") if hasattr(dt, "strftime") else t1
        values = ws2.get_all_values()
        for i in range(6, len(values)):
            row = values[i]
            d = (row[idx_date] if idx_date >= 0 and idx_date < len(row) else "").strip()
            t_raw = (row[idx_time] if idx_time >= 0 and idx_time < len(row) else "").strip()
            try:
                rp = t_raw.split(":")
                t_norm = f"{str(rp[0]).zfill(2)}:{rp[1]}" if len(rp) >= 2 else t_raw
            except Exception:
                t_norm = t_raw
            if (d in (target_date, alt_date)) and (t_raw in (t1, t2) or t_norm in (t1, t2)):
                target_rowno = i + 1
                break
        if target_rowno and idx_status >= 0 and idx_last >= 0:
            now_text = _tz_now().strftime("%Y/%m/%d %H:%M")
            update_data = [{"range": gspread.utils.rowcol_to_a1(target_rowno, idx_status + 1), "values": [["已發車"]]}, {"range": gspread.utils.rowcol_to_a1(target_rowno, idx_last + 1), "values": [[now_text]]}]
            ws2.batch_update(update_data, value_input_option="USER_ENTERED")
            _invalidate_ws_cache("車次管理(櫃台)")
            _invalidate_ws_cache("車次管理(備品)")
    except Exception:
        pass
    if req.driver_role == 'desk':
        return GoogleTripStartResponse(trip_id=trip_id, share_url=None, stops=None)
    try:
        ws = open_ws(SHEET_NAME_SYSTEM)
        e19 = (ws.acell("E19").value or "").strip().lower()
        enabled = e19 in ("true", "t", "yes", "1")
    except Exception:
        enabled = True
    if not enabled:
        return GoogleTripStartResponse(trip_id=trip_id, share_url=None, stops=None)
    STATION_MAP = {"1. 福泰大飯店 (去)": "福泰大飯店 Forte Hotel", "2. 南港捷運站": "南港展覽館捷運站 Nangang Exhibition Center - MRT Exit 3", "3. 南港火車站": "南港火車站 Nangang Train Station", "4. LaLaport 購物中心": "LaLaport Shopping Park", "5. 福泰大飯店 (回)": "福泰大飯店(回) Forte Hotel (Back)"}
    stops_names: List[str] = []
    if req.stops and len(req.stops) > 0:
        for app_station in req.stops:
            mapped = STATION_MAP.get(app_station, app_station)
            if mapped:
                stops_names.append(mapped)
    else:
        STATIONS = ["福泰大飯店 Forte Hotel", "南港展覽館捷運站 Nangang Exhibition Center - MRT Exit 3", "南港火車站 Nangang Train Station", "LaLaport Shopping Park", "福泰大飯店(回) Forte Hotel (Back)"]
        stops_names = STATIONS
    COORDS = {"福泰大飯店 Forte Hotel": {"lat": 25.054964953523683, "lng": 121.63077275881052}, "南港展覽館捷運站 Nangang Exhibition Center - MRT Exit 3": {"lat": 25.055017007293404, "lng": 121.61818547695053}, "南港火車站 Nangang Train Station": {"lat": 25.052822671279454, "lng": 121.60771823129633}, "LaLaport Shopping Park": {"lat": 25.05629820919232, "lng": 121.61700981622211}, "福泰大飯店(回) Forte Hotel (Back)": {"lat": 25.054800375417987, "lng": 121.63117576557792}}
    stops: List[Dict[str, float]] = []
    for name in stops_names:
        coord = COORDS.get(name)
        if coord:
            stops.append({"lat": coord["lat"], "lng": coord["lng"], "name": name})
    polyline_obj: Dict[str, Any] = {}
    try:
        api_key = os.environ.get("GOOGLE_MAPS_API_KEY")
        if api_key and len(stops) >= 2:
            origin = f"{stops[0]['lat']},{stops[0]['lng']}"
            destination = f"{stops[-1]['lat']},{stops[-1]['lng']}"
            if len(stops) > 2:
                wp = "|".join([f"{s['lat']},{s['lng']}" for s in stops[1:-1]])
            else:
                wp = ""
            params = {"origin": origin, "destination": destination, "mode": "driving", "key": api_key}
            if wp:
                params["waypoints"] = wp
            url = "https://maps.googleapis.com/maps/api/directions/json?" + urllib.parse.urlencode(params)
            with urllib.request.urlopen(url, timeout=10) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            if data.get("status") == "OK":
                routes = data.get("routes", [])
                if routes:
                    points = routes[0].get("overview_polyline", {}).get("points", "")
                    def _decode_polyline(poly: str) -> List[Dict[str, float]]:
                        coords: List[Dict[str, float]] = []
                        index, lat, lng = 0, 0, 0
                        while index < len(poly):
                            result, shift = 0, 0
                            while True:
                                b = ord(poly[index]) - 63
                                index += 1
                                result |= (b & 0x1f) << shift
                                shift += 5
                                if b < 0x20:
                                    break
                            dlat = ~(result >> 1) if (result & 1) else (result >> 1)
                            lat += dlat
                            result, shift = 0, 0
                            while True:
                                b = ord(poly[index]) - 63
                                index += 1
                                result |= (b & 0x1f) << shift
                                shift += 5
                                if b < 0x20:
                                    break
                            dlng = ~(result >> 1) if (result & 1) else (result >> 1)
                            lng += dlng
                            coords.append({"lat": lat / 1e5, "lng": lng / 1e5})
                        return coords
                    path = _decode_polyline(points) if points else []
                    polyline_obj = {"points": points, "path": path}
    except Exception:
        pass
    try:
        if not firebase_admin._apps:
            service_account_path = "service_account.json"
            if os.path.exists(service_account_path):
                cred = credentials.Certificate(service_account_path)
            else:
                cred = credentials.ApplicationDefault()
            db_url = os.environ.get("FIREBASE_RTDB_URL")
            if not db_url:
                project_id = os.environ.get("GOOGLE_CLOUD_PROJECT", "shuttle-system-487204")
                db_url = f"https://{project_id}-default-rtdb.asia-southeast1.firebasedatabase.app/"
            firebase_admin.initialize_app(cred, {"databaseURL": db_url})
        payload = {"stops": stops}
        if polyline_obj:
            payload["polyline"] = polyline_obj
        try:
            db.reference("/current_trip_id").set(trip_id)
            db.reference("/current_trip_status").set("active")
            db.reference("/current_trip_datetime").set(req.main_datetime)
            db.reference("/current_trip_route").set(payload)
            db.reference("/gps_system_enabled").set(enabled)
            db.reference("/current_trip_start_time").set(int(time.time() * 1000))
            db.reference("/current_trip_completed_stops").set([])
            STATIONS = ["福泰大飯店 Forte Hotel", "南港展覽館捷運站 Nangang Exhibition Center - MRT Exit 3", "南港火車站 Nangang Train Station", "LaLaport Shopping Park", "福泰大飯店(回) Forte Hotel (Back)"]
            stations_info = {"stops": stops_names, "all_stations": STATIONS}
            db.reference("/current_trip_stations").set(stations_info)
            if stops_names and len(stops_names) > 0:
                first_stop = stops_names[0]
                db.reference("/current_trip_station").set(first_stop)
        except Exception:
            pass
    except Exception:
        pass
    return GoogleTripStartResponse(trip_id=trip_id, share_url=None, stops=stops or None)

@app.post("/api/driver/google/trip_complete")
def api_driver_google_trip_complete(req: GoogleTripCompleteRequest):
    if not req.trip_id:
        raise HTTPException(status_code=400, detail="缺少 trip_id")
    success = auto_complete_trip(trip_id=req.trip_id, main_datetime=req.main_datetime)
    if success:
        return {"status": "success"}
    else:
        raise HTTPException(status_code=500, detail="結束班次失敗")

@app.get("/api/driver/route")
def api_driver_route(trip_id: str = Query(..., description="主班次時間，例如 2025/12/14 14:30")):
    try:
        if not firebase_admin._apps:
            service_account_path = "service_account.json"
            if os.path.exists(service_account_path):
                cred = credentials.Certificate(service_account_path)
            else:
                cred = credentials.ApplicationDefault()
            db_url = os.environ.get("FIREBASE_RTDB_URL")
            if not db_url:
                project_id = os.environ.get("GOOGLE_CLOUD_PROJECT", "shuttle-system-487204")
                db_url = f"https://{project_id}-default-rtdb.asia-southeast1.firebasedatabase.app/"
            firebase_admin.initialize_app(cred, {"databaseURL": db_url})
        ref = db.reference(f"/trip/{trip_id}/route")
        data = ref.get()
        return data or {"stops": [], "polyline": None}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Route read error: {str(e)}")

@app.get("/api/driver/system_status")
def api_driver_system_status():
    try:
        if not firebase_admin._apps:
            service_account_path = "service_account.json"
            if os.path.exists(service_account_path):
                cred = credentials.Certificate(service_account_path)
            else:
                cred = credentials.ApplicationDefault()
            db_url = os.environ.get("FIREBASE_RTDB_URL")
            if not db_url:
                project_id = os.environ.get("GOOGLE_CLOUD_PROJECT", "shuttle-system-487204")
                db_url = f"https://{project_id}-default-rtdb.asia-southeast1.firebasedatabase.app/"
            firebase_admin.initialize_app(cred, {"databaseURL": db_url})
        ref = db.reference("/gps_system_enabled")
        enabled = ref.get()
        if enabled is None:
            enabled = True
        return {"enabled": bool(enabled), "message": "GPS系統總開關狀態"}
    except Exception:
        return {"enabled": True, "message": "讀取失敗，預設啟用"}

@app.post("/api/driver/system_status")
def api_driver_set_system_status(req: SystemStatusRequest):
    try:
        if not firebase_admin._apps:
            service_account_path = "service_account.json"
            if os.path.exists(service_account_path):
                cred = credentials.Certificate(service_account_path)
            else:
                cred = credentials.ApplicationDefault()
            db_url = os.environ.get("FIREBASE_RTDB_URL")
            if not db_url:
                project_id = os.environ.get("GOOGLE_CLOUD_PROJECT", "shuttle-system-487204")
                db_url = f"https://{project_id}-default-rtdb.asia-southeast1.firebasedatabase.app/"
            firebase_admin.initialize_app(cred, {"databaseURL": db_url})
        ref = db.reference("/gps_system_enabled")
        ref.set(bool(req.enabled))
        return {"status": "success", "enabled": bool(req.enabled), "message": "GPS系統總開關狀態已更新"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"寫入失敗: {str(e)}")

@app.post("/api/driver/update_station")
def api_driver_update_station(req: UpdateStationRequest):
    if not req.trip_id or not req.current_station:
        raise HTTPException(status_code=400, detail="缺少 trip_id 或 current_station")
    try:
        if not firebase_admin._apps:
            service_account_path = "service_account.json"
            if os.path.exists(service_account_path):
                cred = credentials.Certificate(service_account_path)
            else:
                cred = credentials.ApplicationDefault()
            db_url = os.environ.get("FIREBASE_RTDB_URL")
            if not db_url:
                project_id = os.environ.get("GOOGLE_CLOUD_PROJECT", "shuttle-system-487204")
                db_url = f"https://{project_id}-default-rtdb.asia-southeast1.firebasedatabase.app/"
            firebase_admin.initialize_app(cred, {"databaseURL": db_url})
        db.reference("/current_trip_station").set(req.current_station)
        return {"status": "success", "current_station": req.current_station}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"更新站點失敗: {str(e)}")

