from __future__ import annotations
import io
import os
import time
import json
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional
import urllib.parse

import qrcode
from fastapi import FastAPI, HTTPException, Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, validator
import gspread
import google.auth


# ---------- 常數 ----------
SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive"
]
SPREADSHEET_ID = "1xp54tKOczklmT8uacW-HMxwV8r0VOR2ui33jYcE2pUQ"
SHEET_NAME = "工作表21"
BASE_URL = "https://booking-manager-995728097341.asia-east1.run.app"


ROUTE_ORDER = [
    "福泰大飯店",
    "南港展覽館-捷運3號出口",
    "南港火車站",
    "南港 LaLaport Shopping Park",
    "福泰大飯店",
]


# ---------- 工具 ----------
def _tz_now_str() -> str:
    os.environ.setdefault("TZ", "Asia/Taipei")
    try:
        time.tzset()
    except Exception:
        pass
    t = time.localtime()
    return f"{t.tm_year}/{t.tm_mon}/{t.tm_mday} {t.tm_hour:02d}:{t.tm_min:02d}"


def _time_hm_from_any(s: str) -> str:
    s = (s or "").strip().replace("：", ":")
    if " " in s and ":" in s:
        return s.split()[-1][:5]
    if ":" in s:
        return s[:5]
    return s


def _display_trip_str(date_iso: str, time_hm: str) -> str:
    y, m, d = date_iso.split("-")
    return f"'%s/%s %s" % (int(m), int(d), time_hm)


def _mmdd_prefix(date_iso: str) -> str:
    y, m, d = date_iso.split("-")
    return f"{int(m):02d}{int(d):02d}"


def _normalize_stop(name: str) -> str:
    mapping = {
        "福泰大飯店": {"福泰大飯店", "Forte Hotel"},
        "南港展覽館-捷運3號出口": {"南港展覽館-捷運3號出口", "南港展覽館捷運站"},
        "南港火車站": {"南港火車站"},
        "南港 LaLaport Shopping Park": {"南港 LaLaport Shopping Park", "LaLaport"},
    }
    raw = (name or "").strip()
    for key, aliases in mapping.items():
        if raw in aliases or raw.lower() in [a.lower() for a in aliases]:
            return key
    return raw


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

    lo, hi = min(pick_idx, drop_idx), max(pick_idx, drop_idx)
    segs = [str(i) for i in range(lo, hi)]
    return pick_idx, drop_idx, ",".join(segs)


# ---------- Google Sheets ----------
def open_sheet() -> gspread.Worksheet:
    credentials, _ = google.auth.default(scopes=SCOPES)
    gc = gspread.authorize(credentials)
    sh = gc.open_by_key(SPREADSHEET_ID)
    return sh.worksheet(SHEET_NAME)


def _read_headers(ws: gspread.Worksheet) -> List[str]:
    headers = ws.row_values(1)
    return [h.strip() for h in headers if h.strip()]


def _read_all_rows(ws: gspread.Worksheet) -> List[List[str]]:
    return ws.get_all_values()


def _find_rows_by_pred(ws: gspread.Worksheet, pred) -> List[int]:
    values = _read_all_rows(ws)
    if not values:
        return []
    headers = values[0]
    result = []
    for i, row in enumerate(values[1:], start=2):
        d = {headers[j]: row[j] if j < len(row) else "" for j in range(len(headers))}
        if pred(d):
            result.append(i)
    return result


def _get_max_seq_for_date(ws: gspread.Worksheet, date_iso: str) -> int:
    headers = _read_headers(ws)
    all_values = _read_all_rows(ws)
    if not all_values or "預約編號" not in headers:
        return 0
    idx = headers.index("預約編號")
    prefix = _mmdd_prefix(date_iso)
    max_seq = 0
    for row in all_values[1:]:
        if len(row) <= idx:
            continue
        booking = row[idx]
        if booking.startswith(prefix):
            try:
                seq = int(booking[len(prefix):])
                max_seq = max(max_seq, seq)
            except:
                pass
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
app = FastAPI(title="Shuttle Ops API", version="1.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://hotel-web-995728097341.asia-east1.run.app",
        "http://127.0.0.1:8080",
        "http://localhost:8080",
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
    decoded_code = urllib.parse.unquote(code)
    img = qrcode.make(decoded_code)
    bio = io.BytesIO()
    img.save(bio, format="PNG")
    return Response(content=bio.getvalue(), media_type="image/png")


# ---------- 主 API ----------
@app.post("/api/ops")
def ops(req: OpsRequest):
    ws = open_sheet()
    headers = _read_headers(ws)
    action = req.action.lower().strip()
    data = req.data or {}

    # ===== 新增預約 =====
    if action == "book":
        p = BookPayload(**data)
        last_seq = _get_max_seq_for_date(ws, p.date)
        booking_id = f"{_mmdd_prefix(p.date)}{last_seq + 1:03d}"
        car_display = _display_trip_str(p.date, _time_hm_from_any(p.time))
        pk_idx, dp_idx, seg_str = _compute_indices_and_segments(p.direction, p.pickLocation, p.dropLocation)
        qr_content = f"FORTEXZ:{booking_id}"
        qr_url = f"{BASE_URL}/api/qr/{urllib.parse.quote(qr_content)}"

        row_data = {
            "預約編號": booking_id,
            "申請日期": _tz_now_str(),
            "預約狀態": "已預約",
            "姓名": p.name,
            "手機": p.phone,
            "信箱": p.email,
            "身分": "住宿貴賓" if p.identity == "hotel" else "用餐貴賓",
            "房號": p.roomNumber or "",
            "入住日期": p.checkIn or "",
            "退房日期": p.checkOut or "",
            "用餐日期": p.diningDate or "",
            "往返": p.direction,
            "上車地點": p.pickLocation,
            "下車地點": p.dropLocation,
            "車次": car_display,
            "預約人數": p.passengers,
            "上車索引": pk_idx,
            "下車索引": dp_idx,
            "涉及路段範圍": seg_str,
            "QR編碼": qr_content,
        }

        newrow = [row_data.get(h, "") for h in headers]
        ws.append_row(newrow, value_input_option="USER_ENTERED")

        return {"status": "success", "booking_id": booking_id, "qr_url": qr_url, "qr_content": qr_content}

    # ===== 查詢 =====
    elif action == "query":
        p = QueryPayload(**data)
        if not (p.booking_id or p.phone or p.email):
            raise HTTPException(400, "至少提供 booking_id / phone / email 其中一項")
        all_rows = _read_all_rows(ws)
        results = []
        hdrs = all_rows[0]
        now = datetime.now()
        for row in all_rows[1:]:
            rec = {hdrs[i]: row[i] if i < len(row) else "" for i in range(len(hdrs))}
            if p.booking_id and rec.get("預約編號") != p.booking_id:
                continue
            if p.phone and rec.get("手機") != p.phone:
                continue
            if p.email and rec.get("信箱") != p.email:
                continue
            if rec.get("櫃台審核") == "n":
                rec["預約狀態"] = "已拒絕"
            results.append(rec)
        return results

    # ===== 修改 =====
    elif action == "modify":
        p = ModifyPayload(**data)
        target = _find_rows_by_pred(ws, lambda r: r.get("預約編號") == p.booking_id)
        if not target:
            raise HTTPException(404, "找不到此預約編號")
        rowno = target[0]
        row_data = ws.row_values(rowno)
        headers = _read_headers(ws)
        row_map = {headers[i]: row_data[i] if i < len(row_data) else "" for i in range(len(headers))}

        if row_map.get("櫃台審核") == "n":
            raise HTTPException(403, "此預約已被櫃台拒絕，無法修改")

        ws.update_cell(rowno, headers.index("預約狀態") + 1, "已預約")
        ws.update_cell(rowno, headers.index("最後操作時間") + 1, f"{_tz_now_str()} 已修改")
        return {"status": "success", "booking_id": p.booking_id}

    # ===== 刪除 =====
    elif action == "delete":
        p = DeletePayload(**data)
        target = _find_rows_by_pred(ws, lambda r: r.get("預約編號") == p.booking_id)
        if not target:
            raise HTTPException(404, "找不到此預約編號")
        rowno = target[0]
        row_data = ws.row_values(rowno)
        headers = _read_headers(ws)
        row_map = {headers[i]: row_data[i] if i < len(row_data) else "" for i in range(len(headers))}

        if row_map.get("櫃台審核") == "n":
            raise HTTPException(403, "此預約已被櫃台拒絕，無法刪除")

        ws.update_cell(rowno, headers.index("預約狀態") + 1, "已刪除")
        ws.update_cell(rowno, headers.index("最後操作時間") + 1, f"{_tz_now_str()} 已刪除")
        return {"status": "success", "booking_id": p.booking_id}

    # ===== 掃碼上車 =====
    elif action == "check_in":
        p = CheckInPayload(**data)
        if not (p.code or p.booking_id):
            raise HTTPException(400, "需提供 code 或 booking_id")
        target = _find_rows_by_pred(ws, lambda r: r.get("QR編碼") == p.code or r.get("預約編號") == p.booking_id)
        if not target:
            raise HTTPException(404, "找不到符合條件之訂單")
        rowno = target[0]
        ws.update_cell(rowno, headers.index("乘車狀態") + 1, "已上車")
        ws.update_cell(rowno, headers.index("最後操作時間") + 1, f"{_tz_now_str()} 已上車")
        return {"status": "success", "row": rowno}

    else:
        raise HTTPException(400, f"未知 action：{action}")


@app.get("/api/debug")
def debug_endpoint():
    return {"status": "服務正常", "base_url": BASE_URL, "time": _tz_now_str()}
