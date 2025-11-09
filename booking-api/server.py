# booking-api/server.py
import os
import io
import base64
from typing import Dict, Any
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import gspread
from google.oauth2.service_account import Credentials
from google.auth import default as google_auth_default
from datetime import datetime
from zoneinfo import ZoneInfo
import qrcode

# ---------- Config ----------
SPREADSHEET_ID = os.getenv("SPREADSHEET_ID", "1xp54tKOczklmT8uacW-HMxwV8r0VOR2ui33jYcE2pUQ")
ORDERS_SHEET_NAME = os.getenv("ORDERS_SHEET_NAME", "預約審核(櫃台)")

# ---------- FastAPI ----------
app = FastAPI(title="Hotel Shuttle - Booking API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------- Google Sheets client ----------
def _gspread_client():
    sa_json = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON")
    scopes = ["https://www.googleapis.com/auth/spreadsheets"]
    if sa_json:
        info = io.StringIO(sa_json).getvalue()
        creds = Credentials.from_service_account_info(eval(info), scopes=scopes) if info.strip().startswith("{") else None
        if creds is None:
            # If env contains JSON string directly
            creds = Credentials.from_service_account_info(eval(sa_json), scopes=scopes)
        return gspread.authorize(creds)
    # fallback to default credentials (Cloud Run)
    creds, _ = google_auth_default(scopes=scopes)
    return gspread.authorize(creds)

def _open_orders_ws():
    gc = _gspread_client()
    sh = gc.open_by_key(SPREADSHEET_ID)
    try:
        return sh.worksheet(ORDERS_SHEET_NAME)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"無法開啟工作表：{ORDERS_SHEET_NAME}, {e}")

# ---------- Helpers ----------
def now_taipei_str():
    tz = ZoneInfo("Asia/Taipei")
    dt = datetime.now(tz)
    # 申請日期：YYYY/M/D HH:MM
    return f"{dt.year}/{dt.month}/{dt.day} {dt.hour:02d}:{dt.minute:02d}"

def m_d_hm_text(date_iso: str, time_hm: str) -> str:
    # 強制純文字格式 M/D HH:MM
    try:
        y, m, d = date_iso.split("-")
        return f"'{int(m)}/{int(d)} {time_hm}"
    except Exception:
        return f"'{date_iso} {time_hm}"

def ymd_text(date_iso: str) -> str:
    # 將 2025-11-09 -> 2025/11/9
    try:
        y, m, d = date_iso.split("-")
        return f"{int(y)}/{int(m)}/{int(d)}"
    except Exception:
        return date_iso

def station_index(name: str, role: str) -> int:
    """role: 'pickup' or 'dropoff'"""
    name = (name or "").strip()
    # 標準化關鍵字
    if "福泰" in name or "Forte Hotel" in name:
        return 1 if role == "pickup" else 5
    if "展覽" in name or "MRT Exit 3" in name or "Exhibition" in name:
        return 2
    if "火車" in name or "Train" in name:
        return 3
    if "LaLaport" in name or "LaLa" in name or "Shopping" in name:
        return 4
    # fallback：未知站點置中
    return 3

def involved_segments(pick_idx: int, drop_idx: int) -> str:
    """回傳不含 drop_idx 的區間，用逗號分隔"""
    if pick_idx >= drop_idx:
        # 防呆：仍以升冪列出，避免回圈
        rng = list(range(min(pick_idx, drop_idx), max(pick_idx, drop_idx)))
    else:
        rng = list(range(pick_idx, drop_idx))
    return ",".join(str(x) for x in rng)

def build_qr_text(booking_id: str) -> str:
    return f"FORTEXIZHI|{booking_id}"

def qr_png_data_uri(text: str) -> str:
    img = qrcode.make(text)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    b64 = base64.b64encode(buf.getvalue()).decode("utf-8")
    return f"data:image/png;base64,{b64}"

def ensure_headers(ws) -> Dict[str, int]:
    headers = ws.row_values(1)
    header_map = {h: i for i, h in enumerate(headers)}
    required = [
        "預約編號","申請日期","乘車狀態","姓名","手機","信箱","往返","日期","車次",
        "上車地點","下車地點","預約人數","確認人數","櫃台審核","備註",
        "上車索引","下車索引","涉及路段範圍","QR編碼","操作紀錄"
    ]
    changed = False
    for h in required:
        if h not in header_map:
            headers.append(h)
            header_map[h] = len(headers) - 1
            changed = True
    if changed:
        ws.update('1:1', [headers])
    return header_map

def next_booking_id(ws) -> str:
    # 以 MMDD + 3位流水號
    headers = ws.row_values(1)
    try:
        col_idx = headers.index("預約編號") + 1
    except ValueError:
        col_idx = None
    rows = ws.get_all_values()
    # 今日的 MMDD
    tz = ZoneInfo("Asia/Taipei")
    dt = datetime.now(tz)
    prefix = f"{dt.month:02d}{dt.day:02d}"  # MMDD
    max_seq = 0
    if col_idx:
        for r in rows[1:]:
            if len(r) >= col_idx:
                bid = r[col_idx - 1].strip()
                # 支援舊格式：可能是 YYMMDDNNN
                if bid.startswith(prefix):
                    tail = bid[len(prefix):]
                    try:
                        n = int(tail[-3:])
                        if n > max_seq:
                            max_seq = n
                    except Exception:
                        continue
                elif len(bid) >= 9 and bid[2:6] == prefix:
                    # 舊格式 25 + MMDD + NNN
                    tail = bid[-3:]
                    try:
                        n = int(tail)
                        if n > max_seq:
                            max_seq = n
                    except Exception:
                        continue
    return f"{prefix}{max_seq+1:03d}"

def set_by_header(row: list, header_map: Dict[str, int], key: str, value: Any):
    idx = header_map[key]
    # 擴展長度
    if len(row) <= idx:
        row += [""] * (idx + 1 - len(row))
    row[idx] = "" if value is None else str(value)

# ---------- Routes ----------
@app.post("/api/book")
def book(payload: Dict[str, Any]):
    """
    請求格式（前端既有）：
    {
      direction, date, station, time, identity,
      checkIn, checkOut, diningDate, roomNumber,
      name, phone, email, passengers,
      dropLocation, pickLocation
    }
    """
    required = ["direction", "date", "time", "name", "phone", "email", "passengers", "pickLocation", "dropLocation"]
    for k in required:
        if k not in payload or payload[k] in (None, ""):
            raise HTTPException(status_code=400, detail=f"缺少必填欄位：{k}")
    ws = _open_orders_ws()
    header_map = ensure_headers(ws)

    booking_id = next_booking_id(ws)
    qr_text = build_qr_text(booking_id)
    qr_data_uri = qr_png_data_uri(qr_text)

    # 計算索引與區間
    pick_idx = station_index(payload["pickLocation"], "pickup")
    drop_idx = station_index(payload["dropLocation"], "dropoff")
    segments = involved_segments(pick_idx, drop_idx)

    # 建列
    row = [""] * (len(header_map))
    set_by_header(row, header_map, "預約編號", booking_id)
    set_by_header(row, header_map, "申請日期", now_taipei_str())
    set_by_header(row, header_map, "乘車狀態", "未上車")
    set_by_header(row, header_map, "姓名", payload.get("name"))
    set_by_header(row, header_map, "手機", payload.get("phone"))
    set_by_header(row, header_map, "信箱", payload.get("email"))
    set_by_header(row, header_map, "往返", payload.get("direction"))
    set_by_header(row, header_map, "日期", ymd_text(payload.get("date")))
    set_by_header(row, header_map, "車次", m_d_hm_text(payload.get("date"), payload.get("time")))
    set_by_header(row, header_map, "上車地點", payload.get("pickLocation"))
    set_by_header(row, header_map, "下車地點", payload.get("dropLocation"))
    set_by_header(row, header_map, "預約人數", payload.get("passengers"))
    set_by_header(row, header_map, "確認人數", "")
    set_by_header(row, header_map, "櫃台審核", "")
    set_by_header(row, header_map, "備註", "")
    set_by_header(row, header_map, "上車索引", pick_idx)
    set_by_header(row, header_map, "下車索引", drop_idx)
    set_by_header(row, header_map, "涉及路段範圍", segments)
    set_by_header(row, header_map, "QR編碼", qr_text)
    set_by_header(row, header_map, "操作紀錄", "")

    # 可能存在之欄位（僅當表頭存在才寫）
    opt_fields = {
        "房號": payload.get("roomNumber"),
        "入住日期": ymd_text(payload.get("checkIn")) if payload.get("checkIn") else "",
        "退房日期": ymd_text(payload.get("checkOut")) if payload.get("checkOut") else "",
        "用餐日期": ymd_text(payload.get("diningDate")) if payload.get("diningDate") else ""
    }
    for k, v in opt_fields.items():
        if k in header_map:
            set_by_header(row, header_map, k, v)

    # 寫入
    ws.append_row(row, value_input_option="USER_ENTERED")

    return {
        "status": "success",
        "booking_id": booking_id,
        "qr_url": qr_data_uri,
        "ticket_url": None
    }
