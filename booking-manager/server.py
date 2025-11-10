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
    "申請日期": {"申請日期", "建立時間"},
    "最後操作時間": {"最後操作時間", "最後更新時間"},
    "預約編號": {"預約編號", "訂單編號"},
    "往返": {"往返", "方向"},
    "日期": {"日期", "出發日期"},
    "班次": {"班次", "時間"},
    "車次": {"車次", "顯示車次"},
    "上車地點": {"上車地點", "上車站點"},
    "下車地點": {"下車地點", "下車站點"},
    "姓名": {"姓名", "name"},
    "手機": {"手機", "電話"},
    "信箱": {"信箱", "email"},
    "預約人數": {"預約人數", "人數"},
    "櫃台審核": {"櫃台審核", "審核"},
    "預約狀態": {"預約狀態", "狀態"},
    "乘車狀態": {"乘車狀態", "乘車"},
    "身分": {"身分"},
    "房號": {"房號"},
    "入住日期": {"入住日期"},
    "退房日期": {"退房日期"},
    "用餐日期": {"用餐日期"},
    "上車索引": {"上車索引"},
    "下車索引": {"下車索引"},
    "涉及路段範圍": {"涉及路段範圍"},
    "QRCode編碼": {"QRCode編碼", "QR內容"},
}

STOP_ALIASES = {
    "福泰大飯店": {"福泰大飯店", "Forte Hotel"},
    "南港展覽館-捷運3號出口": {"南港展覽館-捷運3號出口", "南港展覽館捷運站"},
    "南港火車站": {"南港火車站"},
    "南港 LaLaport Shopping Park": {"南港 LaLaport Shopping Park", "LaLaport"},
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
    os.environ.setdefault("TZ", "Asia/Taipei")
    try: time.tzset()
    except Exception: pass
    t = time.localtime()
    return f"{t.tm_year}/{t.tm_mon}/{t.tm_mday} {t.tm_hour:02d}:{t.tm_min:02d}"

def _display_trip_str(date_iso: str, time_hm: str) -> str:
    y, m, d = date_iso.split("-")
    return f"'%s/%s %s" % (int(m), int(d), time_hm)

def _time_hm_from_any(s: str) -> str:
    s = (s or "").strip().replace("：", ":")
    if " " in s and ":" in s:
        return s.split()[-1][:5]
    if ":" in s: return s[:5]
    return s

def _compute_indices_and_segments(direction: str, pickup: str, dropoff: str):
    norm_pick = _normalize_stop(pickup)
    norm_drop = _normalize_stop(dropoff)
    def base_index(stop: str) -> int:
        for i, s in enumerate(ROUTE_ORDER, start=1):
            if stop == s: return i
        return 0
    pick_idx = base_index(norm_pick)
    drop_idx = base_index(norm_drop)
    if norm_pick == "福泰大飯店" and direction == "去程": pick_idx = 1
    if norm_drop == "福泰大飯店" and direction == "回程": drop_idx = 5
    lo, hi = min(pick_idx, drop_idx), max(pick_idx, drop_idx)
    segs = [str(i) for i in range(lo, max(lo, hi))]
    if segs and segs[-1] == str(hi): segs.pop()
    return pick_idx, drop_idx, ",".join(segs)

def _mmdd_prefix(date_iso: str) -> str:
    y, m, d = date_iso.split("-")
    return f"{int(m):02d}{int(d):02d}"

# ---------- Google Sheets ----------
def open_sheet() -> gspread.Worksheet:
    json_path = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON")
    if not json_path or not os.path.exists(json_path):
        raise RuntimeError("找不到 GOOGLE_SERVICE_ACCOUNT_JSON 憑證檔")
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]
    creds = Credentials.from_service_account_file(json_path, scopes=scopes)
    gc = gspread.authorize(creds)
    spreadsheet_id = os.getenv("SPREADSHEET_ID")
    if not spreadsheet_id:
        raise RuntimeError("請設定 SPREADSHEET_ID")
    sh = gc.open_by_key(spreadsheet_id)
    ws = sh.worksheet(os.getenv("SHEET_NAME", DEFAULT_SHEET_NAME))
    return ws

def header_map(ws: gspread.Worksheet) -> Dict[str, int]:
    row = ws.row_values(1)
    m: Dict[str, int] = {}
    for idx, name in enumerate(row, start=1):
        name = (name or "").strip()
        if not name: continue
        for std, aliases in HEADER_ALIASES.items():
            if name == std or name in aliases:
                if std not in m:
                    m[std] = idx
    return m

def _read_all_rows(ws: gspread.Worksheet) -> List[List[str]]:
    return ws.get_all_values()

def _find_rows_by_pred(ws: gspread.Worksheet, pred) -> List[int]:
    values = _read_all_rows(ws)
    if not values: return []
    headers = values[0]
    result = []
    for i, row in enumerate(values[1:], start=2):
        d = {headers[j]: row[j] if j < len(row) else "" for j in range(len(headers))}
        if pred(d): result.append(i)
    return result

def _get_max_seq_for_date(ws: gspread.Worksheet, date_iso: str) -> int:
    m = header_map(ws)
    all_values = _read_all_rows(ws)
    if not all_values: return 0
    try: c_id = m["預約編號"]
    except KeyError: return 0
    prefix = _mmdd_prefix(date_iso)
    max_seq = 0
    for row in all_values[1:]:
        booking = row[c_id - 1] if c_id - 1 < len(row) else ""
        if booking.startswith(prefix):
            try:
                seq = int(booking[len(prefix):])
                max_seq = max(max_seq, seq)
            except: pass
    return max_seq

# ---------- Pydantic ----------
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

class DeletePayload(BaseModel):
    booking_id: str

class CheckInPayload(BaseModel):
    code: Optional[str] = None
    booking_id: Optional[str] = None

class OpsRequest(BaseModel):
    action: str
    data: Dict[str, Any]

# ---------- FastAPI ----------
app = FastAPI(title="Shuttle Ops API", version="1.0.2")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://hotel-web-995728097341.asia-east1.run.app",
        "http://127.0.0.1:8080",
        "http://localhost:8080"
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

# ---------- 主 API ----------
@app.post("/api/ops")
def ops(req: OpsRequest):
    action = (req.action or "").strip().lower()
    data = req.data or {}
    ws = open_sheet()
    hmap = header_map(ws)

    # ===== 新增預約 =====
    if action == "book":
        p = BookPayload(**data)
        last_seq = _get_max_seq_for_date(ws, p.date)
        booking_id = f"{_mmdd_prefix(p.date)}{last_seq+1:03d}"
        car_display = _display_trip_str(p.date, _time_hm_from_any(p.time))
        pk_idx, dp_idx, seg_str = _compute_indices_and_segments(p.direction, p.pickLocation, p.dropLocation)
        qr_content = f"FORTEXZ:{booking_id}"

        headers = _read_all_rows(ws)[0]
        newrow = [""] * len(headers)
        def setv(col, v):
            if col in hmap:
                newrow[hmap[col]-1] = str(v)
        setv("申請日期", _tz_now_str())
        setv("預約編號", booking_id)
        setv("往返", p.direction)
        setv("日期", p.date)
        setv("班次", _time_hm_from_any(p.time))
        setv("車次", car_display)
        setv("上車地點", p.pickLocation)
        setv("下車地點", p.dropLocation)
        setv("姓名", p.name)
        setv("手機", p.phone)
        setv("信箱", p.email)
        setv("預約人數", p.passengers)
        setv("預約狀態", "已預約")
        setv("乘車狀態", "")
        setv("身分", "住宿貴賓" if p.identity == "hotel" else "用餐貴賓")
        setv("房號", p.roomNumber or "")
        setv("入住日期", p.checkIn or "")
        setv("退房日期", p.checkOut or "")
        setv("用餐日期", p.diningDate or "")
        setv("上車索引", pk_idx)
        setv("下車索引", dp_idx)
        setv("涉及路段範圍", seg_str)
        setv("QRCode編碼", qr_content)
        ws.append_row(newrow, value_input_option="USER_ENTERED")
        return {"status": "success", "booking_id": booking_id, "qr_url": f"/api/qr/{qr_content}"}

    # ===== 查詢 =====
    elif action == "query":
        p = QueryPayload(**data)
        if not (p.booking_id or p.phone or p.email):
            raise HTTPException(400, "至少提供 booking_id / phone / email 其中一項")
        all_values = _read_all_rows(ws)
        if not all_values: return []
        headers = all_values[0]
        now, one_month_ago = datetime.now(), datetime.now() - timedelta(days=31)
        def get(row, key):
            return row[hmap[key]-1] if key in hmap and len(row)>=hmap[key] else ""
        results=[]
        for row in all_values[1:]:
            date_iso = get(row, "日期")
            try: d = datetime.strptime(date_iso, "%Y-%m-%d")
            except: d = now
            if d < one_month_ago: continue
            if p.booking_id and p.booking_id != get(row, "預約編號"): continue
            if p.phone and p.phone != get(row, "手機"): continue
            if p.email and p.email != get(row, "信箱"): continue
            results.append({k: get(row, k) for k in hmap})
        return results

    # ===== 修改 =====
    elif action == "modify":
        p = ModifyPayload(**data)
        target = _find_rows_by_pred(ws, lambda r: r.get("預約編號") == p.booking_id)
        if not target: raise HTTPException(404, "找不到此預約編號")
        rowno = target[0]
        updates = {"最後操作時間": _tz_now_str()+" 已修改", "預約狀態": "已預約"}
        for k,v in updates.items():
            ws.update_cell(rowno, hmap[k], v)
        return {"status": "success", "booking_id": p.booking_id}

    # ===== 刪除 =====
    elif action == "delete":
        p = DeletePayload(**data)
        target = _find_rows_by_pred(ws, lambda r: r.get("預約編號") == p.booking_id)
        if not target: raise HTTPException(404, "找不到此預約編號")
        rowno = target[0]
        ws.update_cell(rowno, hmap["預約狀態"], "已刪除")
        ws.update_cell(rowno, hmap["最後操作時間"], _tz_now_str()+" 已刪除")
        return {"status": "success", "booking_id": p.booking_id}

    # ===== 掃碼上車 =====
    elif action == "check_in":
        p = CheckInPayload(**data)
        if not (p.code or p.booking_id):
            raise HTTPException(400, "需提供 code 或 booking_id")
        target = _find_rows_by_pred(ws, lambda r: r.get("QRCode編碼") == p.code or r.get("預約編號") == p.booking_id)
        if not target: raise HTTPException(404, "找不到符合條件之訂單")
        rowno = target[0]
        ws.update_cell(rowno, hmap["乘車狀態"], "已上車")
        ws.update_cell(rowno, hmap["最後操作時間"], _tz_now_str()+" 已上車")
        return {"status": "success", "row": rowno}

    else:
        raise HTTPException(400, f"未知 action：{action}")
