from __future__ import annotations
import io
import os
import re
import time
import base64
import logging
import threading
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple
import urllib.parse
import secrets  

import qrcode
import firebase_admin
from firebase_admin import credentials, db
from fastapi import FastAPI, HTTPException, Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, validator
import gspread
import google.auth
import hashlib
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders
# MIMEImage, PIL.Image, ImageDraw, ImageFont 未使用，已移除

# Email settings
EMAIL_FROM_NAME = "汐止福泰大飯店"
EMAIL_FROM_ADDR = "fortehotels.shuttle@gmail.com"

# ========== 日誌設定 ==========
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("booking-manager")

# ========== 常數與工具 ==========
SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

# Spreadsheet identifiers
SPREADSHEET_ID = "1xp54tKOczklmT8uacW-HMxwV8r0VOR2ui33jYcE2pUQ"
SHEET_NAME_MAIN = "預約審核(櫃台)"      # 主資料表
SHEET_NAME_CAP  = "可預約班次(web)"     # 剩餘可預約名額（權威來源）

# Base URL for generating QR code images
BASE_URL = "https://booking-manager-995728097341.asia-east1.run.app"

# 表頭列開始索引（1-based indexing）
HEADER_ROW_MAIN = 2

# 狀態文本
BOOKED_TEXT = "✔️ 已預約 Booked"
CANCELLED_TEXT = "❌ 已取消 Cancelled"

# ========== 快取設定 ==========
# 目標：在 5 秒 TTL 內，所有讀取 API 都共用同一份 Sheet 資料，避免重複打 Google Sheets
CACHE_TTL_SECONDS = 5

# ========== 併發鎖設定 ==========
# 目標：避免多筆同時預約/修改造成超賣（依日期+班次時間鎖）
LOCK_WAIT_SECONDS = 60
LOCK_STALE_SECONDS = 30
LOCK_POLL_INTERVAL = 2.0

# SHEET_CACHE 結構：
# {
#   "values": List[List[str]] 或 None,
#   "header_map": Dict[str, int] 或 None,
#   "fetched_at": datetime 或 None
# }
SHEET_CACHE: Dict[str, Any] = {
    "values": None,
    "header_map": None,
    "fetched_at": None,
}
CACHE_LOCK = threading.Lock()

# 可預約班次表快取（類似主表快取機制）
CAP_SHEET_CACHE: Dict[str, Any] = {
    "values": None,
    "header_map": None,
    "hdr_row": None,
    "fetched_at": None,
}

# 主表允許欄位
HEADER_KEYS = {
    "申請日期", "最後操作時間", "預約編號", "往返", "日期", "班次", "車次",
    "上車地點", "下車地點", "姓名", "手機", "信箱", "預約人數", "櫃台審核",
    "預約狀態", "乘車狀態", "身分", "房號", "入住日期", "退房日期", "用餐日期",
    "上車索引", "下車索引", "涉及路段範圍", "QRCode編碼", "備註", "寄信狀態",
    "車次-日期時間","主班次時間","確認人數"
}

# 可預約班次表必要欄位
CAP_REQ_HEADERS = ["去程 / 回程", "日期", "班次", "站點", "可預約人數"]

# 站點索引
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

# ========== 工具函數 ==========
def _email_hash6(email: str) -> str:
    return hashlib.sha256((email or "").encode("utf-8")).hexdigest()[:6]

def _tz_now_str() -> str:
    os.environ.setdefault("TZ", "Asia/Taipei")
    try:
        time.tzset()
    except Exception:
        pass
    t = time.localtime()
    return f"{t.tm_year:04d}-{t.tm_mon:02d}-{t.tm_mday:02d} {t.tm_hour:02d}:{t.tm_min:02d}:{t.tm_sec:02d}"

def _today_iso_taipei() -> str:
    os.environ.setdefault("TZ", "Asia/Taipei")
    try:
        time.tzset()
    except Exception:
        pass
    t = time.localtime()
    return f"{t.tm_year:04d}-{t.tm_mon:02d}-{t.tm_mday:02d}"

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

# ========== Google Sheets ==========
def open_ws(name: str) -> gspread.Worksheet:
    try:
        credentials, _ = google.auth.default(scopes=SCOPES)
        gc = gspread.authorize(credentials)
        sh = gc.open_by_key(SPREADSHEET_ID)
        ws = sh.worksheet(name)
        return ws
    except Exception as e:
        raise RuntimeError(f"無法開啟工作表「{name}」: {str(e)}")

def _sheet_headers(ws: gspread.Worksheet, header_row: int) -> List[str]:
    headers = ws.row_values(header_row)
    return [h.strip() for h in headers]

def header_map_main(ws: Optional[gspread.Worksheet] = None, values: Optional[List[List[str]]] = None) -> Dict[str, int]:
    """
    取得 header_map，可以從 Worksheet 或 values 列表取得
    如果提供 values，則不需要讀取 Sheet（用於快取場景）
    """
    if values is not None:
        # 從 values 列表取得 header（用於快取場景）
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
        # 從 Worksheet 取得 header（傳統方式）
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

# ========== Sheet 讀取快取核心 ==========
def _get_sheet_data_main() -> Tuple[List[List[str]], Dict[str, int]]:
    """
    取得《預約審核(櫃台)》的整張表資料與 header_map。
    - 在 CACHE_TTL_SECONDS 內，如果 cache 有值，直接回傳 cache。
    - 超過 TTL 或 cache 無效時，重新讀取 Google Sheets 並更新 cache。
    """
    now = datetime.now()
    global SHEET_CACHE

    with CACHE_LOCK:
        cached_values = SHEET_CACHE.get("values")
        fetched_at: Optional[datetime] = SHEET_CACHE.get("fetched_at")

        if (
            cached_values is not None
            and fetched_at is not None
            and (now - fetched_at).total_seconds() < CACHE_TTL_SECONDS
        ):
            # 使用快取
            return cached_values, SHEET_CACHE["header_map"]

        # 重新讀取 Sheet
        ws = open_ws(SHEET_NAME_MAIN)
        values = _read_all_rows(ws)
        hmap = header_map_main(values=values)

        SHEET_CACHE = {
            "values": values,
            "header_map": hmap,
            "fetched_at": now,
        }
        return values, hmap


def _invalidate_sheet_cache() -> None:
    """
    寫入操作後呼叫，讓下一次讀取時一定會重新抓最新資料。
    """
    global SHEET_CACHE
    with CACHE_LOCK:
        SHEET_CACHE = {
            "values": None,
            "header_map": None,
            "fetched_at": None,
        }

def _invalidate_cap_sheet_cache() -> None:
    """
    清除可預約班次表快取（當容量發生變化時調用）。
    """
    global CAP_SHEET_CACHE
    with CACHE_LOCK:
        CAP_SHEET_CACHE = {
            "values": None,
            "header_map": None,
            "hdr_row": None,
            "fetched_at": None,
        }

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


def _generate_booking_id_rtdb(today_iso: str) -> str:
    """
    產生 booking_id（日期 + 序號），使用 Firebase RTDB 交易確保原子性
    格式：YYMMDD + 序號（至少 2 位，不足補 0；超過 99 自動擴位）
    """
    if not _init_firebase():
        raise RuntimeError("firebase_init_failed")
    date_key = (today_iso or "").strip()
    # YYMMDD
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


# ========== 容量檢查 ==========
def _find_cap_header_row(values: List[List[str]]) -> int:
    for i in range(min(5, len(values))):
        row = [c.strip() for c in values[i]]
        if "去程 / 回程" in row and "可預約人數" in row:
            return i + 1
    return 1

def _cap_header_map(values: List[List[str]]) -> Tuple[Dict[str,int], int]:
    hdr_row = _find_cap_header_row(values)
    headers = [c.strip() for c in (values[hdr_row-1] if len(values) >= hdr_row else [])]
    m: Dict[str,int] = {}
    for idx, name in enumerate(headers, start=1):
        if name in CAP_REQ_HEADERS and name not in m:
            m[name] = idx
    return m, hdr_row

def _col_letter(col_idx: int) -> str:
    # gspread utils: rowcol_to_a1(1, col) -> "A1"
    return gspread.utils.rowcol_to_a1(1, col_idx).replace("1", "")

def _normalize_text(s: str) -> str:
    return " ".join((s or "").replace("　"," ").split())

def _parse_available(s: str) -> Optional[int]:
    if s is None:
        return None
    m = re.search(r"(\d+)", str(s))
    return int(m.group(1)) if m else None

def _get_cap_sheet_data() -> Tuple[List[List[str]], Dict[str, int], int]:
    """
    取得《可預約班次(web)》的整張表資料與 header_map。
    使用快取機制減少 Google Sheets API 調用。
    """
    now = datetime.now()
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
            # 使用快取
            return cached_values, cached_hmap, cached_hdr_row

        # 重新讀取 Sheet（只讀必要範圍）
        ws_cap = open_ws(SHEET_NAME_CAP)
        try:
            # 先讀取前 10 列的標題範圍（避免整張表）
            head_chunk = ws_cap.get("A1:AZ10")
            hdr_row = _find_cap_header_row(head_chunk)
            headers = [c.strip() for c in (head_chunk[hdr_row - 1] if len(head_chunk) >= hdr_row else [])]
            m_full: Dict[str, int] = {}
            for idx, name in enumerate(headers, start=1):
                if name in CAP_REQ_HEADERS and name not in m_full:
                    m_full[name] = idx

            # 如果必要欄位不齊，fallback 讀整張表
            if any(key not in m_full for key in CAP_REQ_HEADERS):
                raise ValueError("cap headers not found in head chunk")

            min_idx = min(m_full[k] for k in CAP_REQ_HEADERS)
            max_idx = max(m_full[k] for k in CAP_REQ_HEADERS)
            start_col = _col_letter(min_idx)
            end_col = _col_letter(max_idx)
            # 從標題列一路讀到最後一列（僅必要欄位區間）
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
    # 使用快取機制，減少 Google Sheets API 調用
    values, m, hdr_row = _get_cap_sheet_data()
    for key in CAP_REQ_HEADERS:
        if key not in m:
            raise HTTPException(409, f"capacity_header_missing:{key}")

    idx_dir   = m["去程 / 回程"]-1
    idx_date  = m["日期"]-1
    idx_time  = m["班次"]-1
    idx_st    = m["站點"]-1
    idx_avail = m["可預約人數"]-1

    want_dir = _normalize_text(direction)
    want_date = date_iso.strip()
    want_time = _time_hm_from_any(time_hm)
    want_station = _normalize_text(station)

    for row in values[hdr_row:]:
        if not any(row):
            continue
        r_dir   = _normalize_text(row[idx_dir] if idx_dir < len(row) else "")
        r_date  = (row[idx_date] if idx_date < len(row) else "").strip()
        r_time  = _time_hm_from_any(row[idx_time] if idx_time < len(row) else "")
        r_st    = _normalize_text(row[idx_st] if idx_st < len(row) else "")
        r_avail = row[idx_avail] if idx_avail < len(row) else ""
        if r_dir == want_dir and r_date == want_date and r_time == want_time and r_st == want_station:
            avail = _parse_available(r_avail)
            if avail is None:
                raise HTTPException(409, "capacity_not_numeric")
            return avail
    raise HTTPException(409, "capacity_not_found")

# ========== 簡化的 Email 功能 ==========
def _send_email_gmail(
    to_email: str,
    subject: str,
    text_body: str,
    attachment: Optional[bytes] = None,
    attachment_filename: str = "ticket.png",
):
    """使用 SMTP 寄信 - 簡化版"""
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
    
    # 純文字內容
    msg.attach(MIMEText(text_body, "plain", "utf-8"))

    # 附件
    if attachment:
        part = MIMEBase("application", "octet-stream")
        part.set_payload(attachment)
        encoders.encode_base64(part)
        part.add_header(
            "Content-Disposition",
            f'attachment; filename="{attachment_filename}"',
        )
        msg.attach(part)

    # 連線 SMTP 寄信
    with smtplib.SMTP(host, port) as server:
        server.ehlo()
        server.starttls()
        server.ehlo()
        server.login(user, password)
        server.sendmail(EMAIL_FROM_ADDR, [to_email], msg.as_string())

# ========== Firebase 併發鎖 ==========
def _init_firebase():
    """初始化 Firebase Admin SDK（用於併發鎖）"""
    try:
        if not firebase_admin._apps:
            service_account_path = "service_account.json"
            if os.path.exists(service_account_path):
                cred = credentials.Certificate(service_account_path)
            else:
                cred = credentials.ApplicationDefault()
            db_url = os.environ.get("FIREBASE_RTDB_URL")
            if not db_url:
                project_id = os.environ.get("GOOGLE_CLOUD_PROJECT", "forte-booking-system")
                db_url = f"https://{project_id}-default-rtdb.asia-southeast1.firebasedatabase.app/"
            firebase_admin.initialize_app(cred, {"databaseURL": db_url})
        return True
    except Exception:
        return False


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
                log.info(
                    f"[cap_lock] acquired lock_id={lock_id} holder={holder} waited_ms={waited_ms} date={lock_date} time={lock_time}"
                )
                return holder
            if isinstance(result, dict):
                seen_holder = result.get("holder")
                seen_ts = result.get("ts")
                seen_date = result.get("date")
                seen_time = result.get("time")
                log.info(
                    f"[cap_lock] poll={poll_no} lock_id={lock_id} seen_holder={seen_holder} seen_ts={seen_ts} "
                    f"seen_date={seen_date} seen_time={seen_time} now_ms={now_ms} stale_ms={stale_ms}"
                )
            else:
                log.info(f"[cap_lock] poll={poll_no} lock_id={lock_id} seen_non_dict={result} now_ms={now_ms}")
        except Exception as e:
            log.warning(
                f"[cap_lock] poll_error lock_id={lock_id} holder={holder} poll={poll_no} type={type(e).__name__} msg={e}"
            )

        time.sleep(0.2)

    waited_ms = int((time.monotonic() - start) * 1000)
    log.warning(
        f"[cap_lock] timeout lock_id={lock_id} holder={holder} waited_ms={waited_ms} date={lock_date} time={lock_time}"
    )
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
            log.warning(
                f"[cap_lock] released_state_error lock_id={lock_id} holder={holder} type={type(e).__name__} msg={e}"
            )
    except Exception as e:
        log.warning(
            f"[cap_lock] release_error lock_id={lock_id} holder={holder} type={type(e).__name__} msg={e}"
        )


def _finalize_capacity_lock(
    lock_id: str,
    holder: str,
    direction: str,
    date_iso: str,
    time_hm: str,
    station: str,
    expected_max: int,
):
    try:
        _invalidate_cap_sheet_cache()
        _wait_capacity_recalc(direction, date_iso, time_hm, station, expected_max)
    except Exception as e:
        log.warning(f"[cap_wait] finalize_error type={type(e).__name__} msg={e}")
    finally:
        _release_capacity_lock(lock_id, holder)


def _wait_capacity_recalc(
    direction: str,
    date_iso: str,
    time_hm: str,
    station: str,
    expected_max: int,
    timeout_s: int = LOCK_WAIT_SECONDS,
):
    start = time.monotonic()
    last_seen = None
    polls = 0
    log.info(
        f"[cap_wait] start dir={direction} date={date_iso} time={time_hm} station={station} expected_max={expected_max}"
    )
    while (time.monotonic() - start) < timeout_s:
        _invalidate_cap_sheet_cache()
        try:
            last_seen = lookup_capacity(direction, date_iso, time_hm, station)
            polls += 1
            log.info(f"[cap_wait] poll={polls} last_seen={last_seen} expected_max={expected_max}")
            if last_seen <= expected_max:
                log.info(
                    f"[cap_wait] done polls={polls} last_seen={last_seen} expected_max={expected_max}"
                )
                return True, last_seen
        except HTTPException as e:
            # 若班次已滿，可能從可預約表消失，視為可預約人數=0
            detail = getattr(e, "detail", "") or ""
            if isinstance(detail, str) and "capacity_not_found" in detail:
                last_seen = 0
                if last_seen <= expected_max:
                    log.info(
                        f"[cap_wait] done_not_found polls={polls} last_seen=0 expected_max={expected_max}"
                    )
                    return True, last_seen
            else:
                last_seen = None
        except Exception as e:
            # Avoid 500 on transient Sheets API errors (e.g. 429 quota)
            last_seen = None
            log.warning(
                f"[cap_wait] poll_error type={type(e).__name__} msg={e} dir={direction} date={date_iso} time={time_hm} station={station}"
            )
            time.sleep(max(LOCK_POLL_INTERVAL, 5.0))
            continue
        time.sleep(LOCK_POLL_INTERVAL)
    log.warning(
        f"[cap_wait] timeout polls={polls} last_seen={last_seen} expected_max={expected_max}"
    )
    return False, last_seen

def _compose_mail_text(info: Dict[str, str], lang: str, kind: str) -> Tuple[str, str]:
    """組合純文字郵件內容 - 雙語版本"""
    
    subjects = {
        "book": {
            "zh": "汐止福泰大飯店接駁車預約確認",
            "en": "Forte Hotel Xizhi Shuttle Reservation Confirmation",
            "ja": "汐止フォルテホテル シャトル予約確認",
            "ko": "포르테 호텔 시즈 셔틀 예약 확인",
        },
        "modify": {
            "zh": "汐止福泰大飯店接駁車預約變更確認",
            "en": "Forte Hotel Xizhi Shuttle Reservation Updated",
            "ja": "汐止フォルテホテル シャトル予約変更完了",
            "ko": "포르테 호텔 시즈 셔틀 예약 변경 완료",
        },
        "cancel": {
            "zh": "汐止福泰大飯店接駁車預約已取消",
            "en": "Forte Hotel Xizhi Shuttle Reservation Canceled",
            "ja": "汐止フォルテホテル シャトル予約キャンセル",
            "ko": "포르테 호텔 시즈 셔틀 예약 취소됨",
        },
    }
    
    # 雙語標題
    subject_zh = subjects[kind]["zh"]
    subject_second = subjects[kind].get(lang, subjects[kind]["en"])
    subject = f"{subject_zh} / {subject_second}"
    
    # 中文內容
    chinese_content = f"""
尊敬的 {info.get('name','')} 貴賓，您好！

您的接駁車預約資訊：

預約編號：{info.get('booking_id','')}
預約班次：{info.get('date','')} {info.get('time','')} (GMT+8)
預約人數：{info.get('pax','')}
往返方向：{info.get('direction','')}
上車站點：{info.get('pick','')}
下車站點：{info.get('drop','')}
手機：{info.get('phone','')}
信箱：{info.get('email','')}

請出示附件中的 QR Code 車票乘車。

如有任何問題，請致電 (02-2691-9222 #1)

汐止福泰大飯店 敬上
"""
    
    # 第二語言內容
    second_content_map = {
        "en": f"""
Dear {info.get('name','')},

Your shuttle reservation details:

Reservation Number: {info.get('booking_id','')}
Reservation Time: {info.get('date','')} {info.get('time','')} (GMT+8)
Number of Guests: {info.get('pax','')}
Direction: {info.get('direction','')}
Pickup Location: {info.get('pick','')}
Dropoff Location: {info.get('drop','')}
Phone: {info.get('phone','')}
Email: {info.get('email','')}

Please present the attached QR code ticket for boarding.

If you have any questions, please call (02-2691-9222 #1)

Best regards,
Forte Hotel Xizhi
""",
        "ja": f"""
{info.get('name','')} 様

シャトル予約の詳細：

予約番号：{info.get('booking_id','')}
便：{info.get('date','')} {info.get('time','')} (GMT+8)
人数：{info.get('pax','')}
方向：{info.get('direction','')}
乗車：{info.get('pick','')}
降車：{info.get('drop','')}
電話：{info.get('phone','')}
メール：{info.get('email','')}

添付のQRコードチケットを提示して乗車してください。

ご質問があれば、(02-2691-9222 #1) までお電話ください。

汐止フルオンホテル
""",
        "ko": f"""
{info.get('name','')} 고객님,

셔틀 예약 내역：

예약번호: {info.get('booking_id','')}
시간: {info.get('date','')} {info.get('time','')} (GMT+8)
인원: {info.get('pax','')}
방향: {info.get('direction','')}
승차: {info.get('pick','')}
하차: {info.get('drop','')}
전화: {info.get('phone','')}
이메일: {info.get('email','')}

첨부된 QR 코드 티켓을 제시하고 탑승하세요.

문의사항이 있으면 (02-2691-9222 #1) 로 전화주세요.

포르테 호텔 시즈
"""
    }
    
    # 選擇第二語言內容（如果語言是中文，則使用英文作為第二語言）
    second_lang = lang if lang in ["en", "ja", "ko"] else "en"
    second_content = second_content_map.get(second_lang, second_content_map["en"])
    
    # 組合雙語內容，中間用分隔線隔開
    separator = "\n" + "="*50 + "\n"
    text_body = chinese_content + separator + second_content
    
    return subject, text_body

# ========== 改良的非同步處理 ==========
def _async_process_mail(
    kind: str,  # "book" / "modify" / "cancel"
    booking_id: str,
    booking_data: Dict[str, Any],
    qr_content: Optional[str],
    lang: str = "zh",
):
    """統一的背景寄信流程 - 簡化版"""
    def _process():
        try:
            ws_main = open_ws(SHEET_NAME_MAIN)
            hmap = header_map_main(ws_main)
            headers = _sheet_headers(ws_main, HEADER_ROW_MAIN)

            # 找到對應的行
            rownos = _find_rows_by_pred(
                ws_main,
                headers,
                HEADER_ROW_MAIN,
                lambda r: r.get("預約編號") == booking_id,
            )
            if not rownos:
                log.error(f"[mail:{kind}] 找不到預約編號 {booking_id} 對應的行")
                return

            rowno = rownos[0]

            # 只在 book / modify 生成 QR Code 附件
            qr_attachment: Optional[bytes] = None
            if kind in ("book", "modify") and qr_content:
                try:
                    # 生成 QR Code 圖片作為附件
                    qr_img = qrcode.make(qr_content)
                    buffer = io.BytesIO()
                    qr_img.save(buffer, format="PNG")
                    qr_attachment = buffer.getvalue()
                    log.info(f"[mail:{kind}] 生成 QR Code 附件成功")
                except Exception as e:
                    log.error(f"[mail:{kind}] 生成 QR Code 附件失敗: {e}")

            try:
                # 使用純文字郵件內容
                subject, text_body = _compose_mail_text(booking_data, lang, kind)
                _send_email_gmail(
                    booking_data["email"],
                    subject,
                    text_body,
                    attachment=qr_attachment,
                    attachment_filename=f"shuttle_ticket_{booking_id}.png" if qr_attachment else None,
                )
                mail_status = f"{_tz_now_str()} 寄信成功({kind})"
                log.info(f"[mail:{kind}] 預約 {booking_id} 寄信成功")
            except Exception as e:
                mail_status = f"{_tz_now_str()} 寄信失敗({kind}): {str(e)}"
                log.error(f"[mail:{kind}] 預約 {booking_id} 寄信失敗: {str(e)}")

            # 更新寄信狀態
            if "寄信狀態" in hmap:
                ws_main.update_acell(
                    gspread.utils.rowcol_to_a1(rowno, hmap["寄信狀態"]),
                    mail_status,
                )

        except Exception as e:
            log.error(f"[mail:{kind}] 非同步處理預約 {booking_id} 時發生錯誤: {str(e)}")

    thread = threading.Thread(target=_process, daemon=True)
    thread.start()

def async_process_after_booking(
    booking_id: str,
    booking_data: Dict[str, Any],
    qr_content: str,
    lang: str = "zh",
):
    _async_process_mail("book", booking_id, booking_data, qr_content, lang)

def async_process_after_modify(
    booking_id: str,
    booking_data: Dict[str, Any],
    qr_content: Optional[str],
    lang: str = "zh",
):
    _async_process_mail("modify", booking_id, booking_data, qr_content, lang)

def async_process_after_cancel(
    booking_id: str,
    booking_data: Dict[str, Any],
    lang: str = "zh",
):
    # cancel 不需要 QR code / 車票
    _async_process_mail("cancel", booking_id, booking_data, qr_content=None, lang=lang)

# ========== 改良的流程控制 ==========
class BookingProcessor:
    def __init__(self):
        self.processing_lock = threading.Lock()
    
    def prepare_booking_row(self, p: BookPayload, booking_id: str, qr_content: str, headers: List[str], hmap: Dict[str, int]) -> List[str]:
        """準備預約資料行"""
        time_hm = _time_hm_from_any(p.time)
        car_display = _display_trip_str(p.date, time_hm)
        pk_idx, dp_idx, seg_str = _compute_indices_and_segments(p.pickLocation, p.dropLocation)
        
        # 計算車次時間
        date_obj = datetime.strptime(p.date, "%Y-%m-%d")
        car_datetime = date_obj.strftime("%Y/%m/%d") + " " + time_hm
        main_departure = _compute_main_departure_datetime(
            p.direction, p.pickLocation, p.date, time_hm
        )
        
        # 準備寫入行
        newrow = [""] * len(headers)
        identity_simple = "住宿" if p.identity == "hotel" else "用餐"
        
        def setv(row_arr: List[str], col: str, v: Any):
            if col in hmap and 1 <= hmap[col] <= len(row_arr):
                row_arr[hmap[col] - 1] = str(v)
        
        # 設置所有欄位
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

    @validator("direction")
    def _v_dir(cls, v):
        if v not in {"去程", "回程"}:
            raise ValueError("方向僅允許 去程 / 回程")
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

# ========== FastAPI ==========
app = FastAPI(title="Shuttle Ops API", version="1.6.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://hotel-web-995728097341.asia-east1.run.app",
        "https://hotel-web-3addcbkbgq-de.a.run.app",
        "http://localhost:8080",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/health")
def health():
    return {"status": "ok", "time": _tz_now_str()}

@app.options("/api/ops")
@app.options("/api/ops/")
def ops_options():
    return Response(status_code=204)

# ========== 主 API ==========
@app.post("/api/ops")
@app.post("/api/ops/")
def ops(req: OpsRequest):
    action = (req.action or "").strip().lower()
    data = req.data or {}
    log.info(f"OPS action={action} payload={data}")
    try:
        # ===== 查詢（使用快取，不需要開啟主表 Worksheet） =====
        if action == "query":
            p = QueryPayload(**data)
            if not (p.booking_id or p.phone or p.email):
                raise HTTPException(400, "至少提供 booking_id / phone / email 其中一項")
            # 使用快取機制，減少 Google Sheets API 調用
            all_values, hmap = _get_sheet_data_main()
            if not all_values:
                return []
            def get(row: List[str], key: str) -> str:
                return row[hmap[key] - 1] if key in hmap and len(row) >= hmap[key] else ""
            now = datetime.now()
            one_month_ago = now - timedelta(days=31)
            results: List[Dict[str, str]] = []
            for row in all_values[HEADER_ROW_MAIN:]:
                # Always derive date/time from unified 車次-日期時間 column if available
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
                        # fallback to legacy columns
                        date_iso = get(row, "日期")
                        time_hm = _time_hm_from_any(get(row, "班次"))
                else:
                    date_iso = get(row, "日期")
                    time_hm = _time_hm_from_any(get(row, "班次"))
                # parse date to filter range; if invalid, use current time to avoid filtering out
                try:
                    d = datetime.strptime(date_iso, "%Y-%m-%d")
                except Exception:
                    d = now
                if d < one_month_ago:
                    continue
                # filter by id/phone/email
                if p.booking_id and p.booking_id != get(row, "預約編號"):
                    continue
                if p.phone and p.phone != get(row, "手機"):
                    continue
                # 信箱查詢使用大小寫不敏感比較
                if p.email:
                    row_email = get(row, "信箱").strip().lower()
                    query_email = p.email.strip().lower()
                    if query_email != row_email:
                        continue
                rec = {k: get(row, k) for k in hmap}
                # override date/time fields with values derived from 車次-日期時間
                if date_iso:
                    rec["日期"] = date_iso
                if time_hm:
                    rec["班次"] = time_hm
                    # update 車次欄以新的顯示格式
                    rec["車次"] = _display_trip_str(date_iso, time_hm)
                # 如果櫃檯審核為 n 則將預約狀態標為「已拒絕」
                if rec.get("櫃台審核", "").lower() == "n":
                    rec["預約狀態"] = "已拒絕"
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

        # ===== 新增預約 =====
        if action == "book":
            p = BookPayload(**data)

            # 先拿班次時間
            time_hm = _time_hm_from_any(p.time)

            # 容量檢查（可預約班次表是權威：可預約人數 = 現存剩餘數）
            station_for_cap = _normalize_station_for_capacity(
                p.direction, p.pickLocation, p.dropLocation
            )
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

                # 產生預約編號：以「今日日期」為準
                today_iso = _today_iso_taipei()
                try:
                    booking_id = _generate_booking_id_rtdb(today_iso)
                except Exception as e:
                    log.warning(f"[booking_id] rtdb_failed type={type(e).__name__} msg={e}")
                    raise HTTPException(503, "暫時無法產生預約編號，請稍後再試")

                # QR 內容
                em6 = _email_hash6(p.email)
                qr_content = f"FT:{booking_id}:{em6}"
                qr_url = f"{BASE_URL}/api/qr/{urllib.parse.quote(qr_content)}"

                # 用 BookingProcessor 統一產生 row（包含主班次時間、車次-日期時間...）
                newrow = booking_processor.prepare_booking_row(
                    p, booking_id, qr_content, headers, hmap
                )

                # 寫入 Google Sheet（關鍵操作）
                ws_main.append_row(newrow, value_input_option="USER_ENTERED")
                wrote = True
                log.info(f"book appended booking_id={booking_id}")
                # 清除快取，確保下次讀取時獲取最新資料
                _invalidate_sheet_cache()
                expected_max = max(0, int(rem) - int(p.passengers))
                # 回應前先啟動背景等待與解鎖，避免前端等待過久
                defer_release = True
                threading.Thread(
                    target=_finalize_capacity_lock,
                    args=(lock_id, lock_holder, p.direction, p.date, time_hm, station_for_cap, expected_max),
                    daemon=True,
                ).start()
            finally:
                if not defer_release:
                    _release_capacity_lock(lock_id, lock_holder)

            # 立即回覆前端 —— 只給前端需要的東西，其他由前端自己維護
            response_data = {
                "status": "success",
                # 給前端用的 camelCase
                "bookingId": booking_id,
                "qrUrl": qr_url,
                "qrContent": qr_content,
                # 順便保留原本的 snake_case，避免前端還沒改完
                "booking_id": booking_id,
                "qr_url": qr_url,
                "qr_content": qr_content,
            }

            # 後端背景寄信（含車票圖片）
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
                
            }
            async_process_after_booking(booking_id, booking_info, qr_content, p.lang)

            return response_data


        # ===== 修改 =====
        elif action == "modify":
            p = ModifyPayload(**data)

            # 找到目標列
            rownos = _find_rows_by_pred(
                ws_main,
                headers,
                HEADER_ROW_MAIN,
                lambda r: r.get("預約編號") == p.booking_id,
            )
            if not rownos:
                raise HTTPException(404, "找不到此預約編號")
            rowno = rownos[0]

            # 讀舊值
            old_dir = get_by_rowno(rowno, "往返")
            old_date = get_by_rowno(rowno, "日期")

            # 舊時間優先從「車次-日期時間」推回來
            old_car_dt = get_by_rowno(rowno, "車次-日期時間")
            if old_car_dt:
                parts = old_car_dt.strip().split()
                old_time = _time_hm_from_any(parts[1] if len(parts) > 1 else parts[0])
            else:
                old_time = _time_hm_from_any(get_by_rowno(rowno, "班次"))

            old_pick = get_by_rowno(rowno, "上車地點")
            old_drop = get_by_rowno(rowno, "下車地點")

            # 舊的人數：優先用確認人數
            try:
                confirm_pax = (get_by_rowno(rowno, "確認人數") or "").strip()
                if confirm_pax:
                    old_pax = int(confirm_pax)
                else:
                    old_pax = int(get_by_rowno(rowno, "預約人數") or "1")
            except Exception:
                old_pax = 1

            # 新值（沒給就用舊值）
            new_dir = p.direction or old_dir
            new_date = p.date or old_date
            new_time = _time_hm_from_any(p.time or old_time)
            new_pick = p.pickLocation or old_pick
            new_drop = p.dropLocation or old_drop
            new_pax = int(p.passengers if p.passengers is not None else old_pax)

            # 容量檢查
            station_for_cap_new = _normalize_station_for_capacity(new_dir, new_pick, new_drop)

            # 如果還是同一班次，只需檢查增加的差額
            same_trip = (
                new_dir,
                new_date,
                new_time,
                _normalize_station_for_capacity(old_dir, old_pick, old_drop),
            ) == (
                old_dir,
                old_date,
                _time_hm_from_any(old_time),
                _normalize_station_for_capacity(old_dir, old_pick, old_drop),
            )

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

                # 開始組更新欄位
                updates: Dict[str, str] = {}
                time_hm = new_time
                car_display = _display_trip_str(new_date, time_hm) if (new_date and time_hm) else None

                # 更新 unified 車次-日期時間 + 主班次時間
                if new_date and new_time:
                    date_obj = datetime.strptime(new_date, "%Y-%m-%d")
                    car_datetime = date_obj.strftime("%Y/%m/%d") + " " + new_time
                    updates["車次-日期時間"] = car_datetime

                    main_departure = _compute_main_departure_datetime(
                        new_dir,
                        new_pick,
                        new_date,
                        new_time,
                    )
                    updates["主班次時間"] = main_departure

                # 站點索引 / 涉及路段
                pk_idx = dp_idx = None
                seg_str = None
                if new_pick and new_drop:
                    pk_idx, dp_idx, seg_str = _compute_indices_and_segments(new_pick, new_drop)

                updates["預約狀態"] = BOOKED_TEXT
                updates["預約人數"] = str(new_pax)

                # 備註增加一條「已修改」
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

                # 信箱 & QRCode 一律用「最終 email」計算
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

                # 寄信狀態改為處理中
                updates["寄信狀態"] = "處理中"

                # 寫回 Google Sheet（batch_update）
                batch_updates = []
                for col_name, value in updates.items():
                    if col_name in hmap:
                        batch_updates.append(
                            {
                                "range": gspread.utils.rowcol_to_a1(rowno, hmap[col_name]),
                                "values": [[value]],
                            }
                        )
                if batch_updates:
                    ws_main.batch_update(batch_updates, value_input_option="USER_ENTERED")
                    wrote = True

                log.info(f"modify updated booking_id={p.booking_id}")
                # 清除快取，確保下次讀取時獲取最新資料
                _invalidate_sheet_cache()

                # 若影響容量，先回應前端，背景等待公式更新後釋放鎖
                if consume > 0 and rem is not None and wrote and lock_holder and lock_id:
                    expected_max = max(0, int(rem) - int(consume))
                    defer_release = True
                    threading.Thread(
                        target=_finalize_capacity_lock,
                        args=(lock_id, lock_holder, new_dir, new_date, new_time, station_for_cap_new, expected_max),
                        daemon=True,
                    ).start()

                # 立即回覆前端
                response_data = {
                    "status": "success",
                    "bookingId": p.booking_id,
                    "booking_id": p.booking_id,
                }

                # 背景寄信
                booking_info = {
                    "booking_id": p.booking_id,
                    "date": new_date,
                    "time": new_time,
                    "direction": new_dir,
                    "pick": new_pick,
                    "drop": new_drop,
                    "name": get_by_rowno(rowno, "姓名"),
                    "phone": p.phone or get_by_rowno(rowno, "手機"),
                    "email": final_email,
                    "pax": str(new_pax),
                    "qr_content": qr_content,
                    "qr_url": f"{BASE_URL}/api/qr/{urllib.parse.quote(qr_content)}" if qr_content else "",
                }
                async_process_after_modify(p.booking_id, booking_info, qr_content, p.lang)
                return response_data
            finally:
                if not defer_release and lock_holder:
                    _release_capacity_lock(lock_id, lock_holder)


        # ===== 刪除（取消） =====
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
            
            # 設置寄信狀態為處理中
            updates["寄信狀態"] = "處理中"
            
            batch_updates = []
            for col_name, value in updates.items():
                if col_name in hmap:
                    batch_updates.append({
                        'range': gspread.utils.rowcol_to_a1(rowno, hmap[col_name]),
                        'values': [[value]]
                    })
            if batch_updates:
                ws_main.batch_update(batch_updates, value_input_option="USER_ENTERED")
            log.info(f"delete updated booking_id={p.booking_id}")
            # 清除快取，確保下次讀取時獲取最新資料
            _invalidate_sheet_cache()
            
            # 立即回覆前端
            response_data = {"status": "success", "booking_id": p.booking_id}
            
            # 非同步處理寄信（取消不需要車票）
            booking_info = {
                "booking_id": p.booking_id,
                "date": get_by_rowno(rowno, "日期"),
                "time": _time_hm_from_any(get_by_rowno(rowno, "班次")),
                "direction": get_by_rowno(rowno, "往返"),
                "pick": get_by_rowno(rowno, "上車地點"),
                "drop": get_by_rowno(rowno, "下車地點"),
                "name": get_by_rowno(rowno, "姓名"),
                "phone": get_by_rowno(rowno, "手機"),
                "email": get_by_rowno(rowno, "信箱"),
                "pax": (
                    get_by_rowno(rowno, "確認人數")
                    or get_by_rowno(rowno, "預約人數")
                    or "1"
                ),
            }
            async_process_after_cancel(p.booking_id, booking_info, p.lang)
            
            return response_data

        # ===== 掃碼上車 =====
        elif action == "check_in":
            p = CheckInPayload(**data)
            if not (p.code or p.booking_id):
                raise HTTPException(400, "需提供 code 或 booking_id")
            rownos = _find_rows_by_pred(
                ws_main, headers, HEADER_ROW_MAIN,
                lambda r: r.get("QRCode編碼") == p.code or r.get("預約編號") == p.booking_id,
            )
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
                    batch_updates.append({
                        'range': gspread.utils.rowcol_to_a1(rowno, hmap[col_name]),
                        'values': [[value]]
                    })
            if batch_updates:
                ws_main.batch_update(batch_updates, value_input_option="USER_ENTERED")
            log.info(f"check_in row={rowno}")
            # 清除快取，確保下次讀取時獲取最新資料
            _invalidate_sheet_cache()
            return {"status": "success", "row": rowno}

        # ===== 寄信（手動補寄） =====
        elif action == "mail":
            p = MailPayload(**data)
            rownos = _find_rows_by_pred(ws_main, headers, HEADER_ROW_MAIN, lambda r: r.get("預約編號") == p.booking_id)
            if not rownos:
                raise HTTPException(404, "找不到此預約編號")
            rowno = rownos[0]
            get = lambda k: get_by_rowno(rowno, k)
            info = {
                "booking_id": get("預約編號"),
                "date": get("日期"),
                "time": _time_hm_from_any(get("班次")),
                "direction": get("往返"),
                "pick": get("上車地點"),
                "drop": get("下車地點"),
                "name": get("姓名"),
                "phone": get("手機"),
                "email": get("信箱"),
                "pax": (get("確認人數") or get("預約人數") or "1"),
            }
            # 使用純文字郵件內容
            subject, text_body = _compose_mail_text(info, p.lang, p.kind)
            attachment_bytes: Optional[bytes] = None
            if p.kind in ("book", "modify") and p.ticket_png_base64:
                b64 = p.ticket_png_base64
                if "," in b64:
                    b64 = b64.split(",", 1)[1]
                try:
                    attachment_bytes = base64.b64decode(b64, validate=True)
                except Exception:
                    attachment_bytes = None
            try:
                _send_email_gmail(
                    info["email"], 
                    subject, 
                    text_body, 
                    attachment=attachment_bytes, 
                    attachment_filename=f"shuttle_ticket_{info['booking_id']}.png" if attachment_bytes else None
                )
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
