
from __future__ import annotations
import io
import os
import re
import json
import time
import urllib.parse
import urllib.request
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

import qrcode
from fastapi import FastAPI, HTTPException, Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, validator
import gspread
import google.auth
import hashlib

# ========== 常數與工具 ==========
SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]
SPREADSHEET_ID = "1xp54tKOczklmT8uacW-HMxwV8r0VOR2ui33jYcE2pUQ"
SHEET_NAME = "預約審核(櫃台)"
BASE_URL = "https://booking-manager-995728097341.asia-east1.run.app"

# 供容量再次驗證的聚合 API（與前端一致）
AGGREGATOR_URL = "https://booking-api-995728097341.asia-east1.run.app/api/sheet"

# 表頭列（1-based）
HEADER_ROW = 2

# 狀態固定字串
BOOKED_TEXT = "✔️ 已預約 Booked"
CANCELLED_TEXT = "❌ 已取消 Cancelled"

# 僅允許精準欄位名稱（不做別名）
HEADER_KEYS = {
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
    "訂單狀態",   # ★ 需求 10
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
    "備註",       # ★ 需求 10
}

# 站點索引（精準雙語字串）
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

def _norm_date(s: str) -> str:
    s = (s or "").strip()
    if re.match(r"^\d{4}-\d{2}-\d{2}$", s):
        return s
    if re.match(r"^\d{4}/\d{1,2}/\d{1,2}$", s):
        y, m, d = s.split("/")
        return f"{int(y):04d}-{int(m):02d}-{int(d):02d}"
    if re.match(r"^\d{1,2}/\d{1,2}/\d{4}$", s):
        m, d, y = s.split("/")
        return f"{int(y):04d}-{int(m):02d}-{int(d):02d}"
    return s

def _digits(n: str) -> int:
    m = re.findall(r"\\d+", str(n or ""))
    return int("".join(m)) if m else 0

# ========== Google Sheets ==========
def open_sheet() -> gspread.Worksheet:
    try:
        credentials, _ = google.auth.default(scopes=SCOPES)
        gc = gspread.authorize(credentials)
        sh = gc.open_by_key(SPREADSHEET_ID)
        ws = sh.worksheet(SHEET_NAME)
        return ws
    except Exception as e:
        raise RuntimeError(f"無法開啟 Google Sheet: {str(e)}")

def _sheet_headers(ws: gspread.Worksheet) -> List[str]:
    headers = ws.row_values(HEADER_ROW)
    return [h.strip() for h in headers]

def header_map(ws: gspread.Worksheet) -> Dict[str, int]:
    row = _sheet_headers(ws)
    m: Dict[str, int] = {}
    for idx, name in enumerate(row, start=1):
        name = (name or "").strip()
        if name in HEADER_KEYS and name not in m:
            m[name] = idx
    return m

def _read_all_rows(ws: gspread.Worksheet) -> List[List[str]]:
    return ws.get_all_values()

def _find_rows_by_pred(ws: gspread.Worksheet, pred) -> List[int]:
    values = _read_all_rows(ws)
    if not values:
        return []
    headers = values[HEADER_ROW - 1] if len(values) >= HEADER_ROW else []
    result = []
    for i, row in enumerate(values[HEADER_ROW:], start=HEADER_ROW + 1):
        if not any(row):
            continue
        d = {headers[j]: row[j] if j < len(row) else "" for j in range(len(headers))}
        if pred(d):
            result.append(i)
    return result

def _get_max_seq_for_date(ws: gspread.Worksheet, date_iso: str) -> int:
    m = header_map(ws)
    all_values = _read_all_rows(ws)
    if not all_values or "預約編號" not in m:
        return 0
    c_id = m["預約編號"]
    prefix = _mmdd_prefix(date_iso)
    max_seq = 0
    for row in all_values[HEADER_ROW:]:
        booking = row[c_id - 1] if c_id - 1 < len(row) else ""
        if booking.startswith(prefix):
            try:
                seq = int(booking[len(prefix):])
                max_seq = max(max_seq, seq)
            except:
                pass
    return max_seq

# ========== 聚合容量查詢 ==========
def _fetch_agg_rows() -> Tuple[List[str], List[List[str]]]:
    """取回 aggregator 原始資料：第一列 headers、其後 rows。失敗則拋錯。"""
    try:
        with urllib.request.urlopen(AGGREGATOR_URL, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        if not (isinstance(data, list) and data and isinstance(data[0], list)):
            raise RuntimeError("Aggregator 回傳格式異常")
        headers = data[0]
        rows = data[1:]
        return headers, rows
    except Exception as e:
        raise HTTPException(503, f"目前無法確認剩餘座位，請稍後再試：{e}")

def _col_idx(headers: List[str], candidates: List[str]) -> Optional[int]:
    for name in candidates:
        if name in headers:
            return headers.index(name)
    return None

def _match_value(a: str, b: str) -> bool:
    return (a or "").strip() == (b or "").strip()

def _available_seats_from_agg(direction: str, date_iso: str, station: str, time_hm: str) -> int:
    """以方向/日期/站點/時間查 aggregator 的『可預約人數』。找不到回 0。"""
    headers, rows = _fetch_agg_rows()
    idx_dir = _col_idx(headers, ["去程 / 回程"])
    idx_date = _col_idx(headers, ["日期"])
    idx_time = _col_idx(headers, ["班次"])
    idx_st  = _col_idx(headers, ["站點"])
    idx_av  = _col_idx(headers, ["可預約人數", "可約人數 / Available"])
    if None in (idx_dir, idx_date, idx_time, idx_st, idx_av):
        raise HTTPException(503, "Aggregator 欄位不足，無法確認剩餘座位")

    tgt_date = _norm_date(date_iso)
    tgt_time = _time_hm_from_any(time_hm)
    for r in rows:
        r_dir  = r[idx_dir] if idx_dir < len(r) else ""
        r_date = _norm_date(r[idx_date] if idx_date < len(r) else "")
        r_time = _time_hm_from_any(r[idx_time] if idx_time < len(r) else "")
        r_st   = r[idx_st] if idx_st < len(r) else ""
        if _match_value(r_dir, direction) and _match_value(r_date, tgt_date) and _match_value(r_time, tgt_time) and _match_value(r_st, station):
            return max(0, _digits(r[idx_av] if idx_av < len(r) else "0"))
    # 沒找到就視為 0（不可預約）
    return 0

def _check_capacity_for_booking(direction: str, date_iso: str, time_hm: str, pick: str, drop: str, passengers: int):
    """新增預約之容量檢查。"""
    # 聚合站點鍵與前端一致：
    agg_station = pick if direction == "回程" else drop
    avail = _available_seats_from_agg(direction, date_iso, agg_station, time_hm)
    if passengers > avail:
        raise HTTPException(400, f"超過可預約人數（剩餘 {avail} 人）")

def _check_capacity_for_modify(ws: gspread.Worksheet, hmap: Dict[str, int], rowno: int, new_direction: str, new_date: str, new_time: str, new_pick: str, new_drop: str, new_passengers: int):
    """修改預約之容量檢查：同班次可 +本人佔位"""
    def get_cell(col: str) -> str:
        if col not in hmap:
            return ""
        return ws.cell(rowno, hmap[col]).value or ""

    old_direction = get_cell("往返")
    old_date      = get_cell("日期")
    old_time      = get_cell("班次")
    old_pick      = get_cell("上車地點")
    old_drop      = get_cell("下車地點")
    try:
        old_pax = int(get_cell("預約人數") or "0")
    except:
        old_pax = 0

    # aggregator 站點鍵
    old_station = old_pick if old_direction == "回程" else old_drop
    new_station = new_pick if new_direction == "回程" else new_drop

    same_trip = (
        _match_value(old_direction, new_direction) and
        _match_value(_norm_date(old_date), _norm_date(new_date)) and
        _match_value(_time_hm_from_any(old_time), _time_hm_from_any(new_time)) and
        _match_value(old_station, new_station)
    )

    base_avail = _available_seats_from_agg(new_direction, new_date, new_station, new_time)
    allowed = base_avail + (old_pax if same_trip else 0)
    if new_passengers > allowed:
        raise HTTPException(400, f"超過可預約人數（此班次剩餘 {base_avail}，{ '含本人 ' + str(old_pax) if same_trip else '不可含本人' }）")

# ========== Pydantic ==========
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
    phone: Optional[str] = None
    email: Optional[str] = None
    # 備註可由後端自動寫入時間說明

class DeletePayload(BaseModel):
    booking_id: str

class CheckInPayload(BaseModel):
    code: Optional[str] = None
    booking_id: Optional[str] = None

class OpsRequest(BaseModel):
    action: str
    data: Dict[str, Any]

# ========== FastAPI ==========
app = FastAPI(title="Shuttle Ops API", version="1.2.0")

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
    try:
        decoded_code = urllib.parse.unquote(code)
        img = qrcode.make(decoded_code)
        bio = io.BytesIO()
        img.save(bio, format="PNG")
        return Response(content=bio.getvalue(), media_type="image/png")
    except Exception as e:
        raise HTTPException(500, f"QR 生成失敗: {str(e)}")

# ========== 主 API ==========
@app.post("/api/ops")
def ops(req: OpsRequest):
    action = (req.action or "").strip().lower()
    data = req.data or {}

    try:
        ws = open_sheet()
        hmap = header_map(ws)
        headers = _sheet_headers(ws)

        def setv(row_arr: List[str], col: str, v: Any):
            if col in hmap and 1 <= hmap[col] <= len(row_arr):
                row_arr[hmap[col] - 1] = v if isinstance(v, str) else str(v)

        # ===== 新增預約 =====
        if action == "book":
            p = BookPayload(**data)

            # ★ 再次檢查容量
            time_hm = _time_hm_from_any(p.time)
            _check_capacity_for_booking(p.direction, _norm_date(p.date), time_hm, p.pickLocation, p.dropLocation, int(p.passengers))

            last_seq = _get_max_seq_for_date(ws, _norm_date(p.date))
            booking_id = f"{_mmdd_prefix(_norm_date(p.date))}{last_seq + 1:03d}"
            car_display = _display_trip_str(_norm_date(p.date), time_hm)

            pk_idx, dp_idx, seg_str = _compute_indices_and_segments(p.pickLocation, p.dropLocation)

            em6 = _email_hash6(p.email)
            qr_content = f"FT:{booking_id}:{em6}"
            qr_url = f"{BASE_URL}/api/qr/{urllib.parse.quote(qr_content)}"

            newrow = [""] * len(headers)
            setv(newrow, "申請日期", _tz_now_str())
            setv(newrow, "預約狀態", BOOKED_TEXT)
            setv(newrow, "訂單狀態", BOOKED_TEXT)  # ★ 需求 10：同步訂單狀態
            identity_simple = "住宿" if p.identity == "hotel" else "用餐"

            setv(newrow, "預約編號", booking_id)
            setv(newrow, "往返", p.direction)
            setv(newrow, "日期", _norm_date(p.date))
            setv(newrow, "班次", time_hm)
            setv(newrow, "車次", car_display)
            setv(newrow, "上車地點", p.pickLocation)
            setv(newrow, "下車地點", p.dropLocation)
            setv(newrow, "姓名", p.name)
            setv(newrow, "手機", p.phone)
            setv(newrow, "信箱", p.email)
            setv(newrow, "預約人數", int(p.passengers))
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
            # 備註不寫入

            ws.append_row(newrow, value_input_option="USER_ENTERED")
            return {"status": "success", "booking_id": booking_id, "qr_url": qr_url, "qr_content": qr_content}

        # ===== 查詢 =====
        elif action == "query":
            p = QueryPayload(**data)
            if not (p.booking_id or p.phone or p.email):
                raise HTTPException(400, "至少提供 booking_id / phone / email 其中一項")

            all_values = _read_all_rows(ws)
            if not all_values:
                return []

            def get(row: List[str], key: str) -> str:
                return row[hmap[key] - 1] if key in hmap and len(row) >= hmap[key] else ""

            now, one_month_ago = datetime.now(), datetime.now() - timedelta(days=31)
            results: List[Dict[str, str]] = []
            for row in all_values[HEADER_ROW:]:
                date_iso = get(row, "日期")
                try:
                    d = datetime.strptime(_norm_date(date_iso), "%Y-%m-%d")
                except:
                    d = now
                if d < one_month_ago:
                    continue
                if p.booking_id and p.booking_id != get(row, "預約編號"):
                    continue
                if p.phone and p.phone != get(row, "手機"):
                    continue
                if p.email and p.email != get(row, "信箱"):
                    continue
                rec = {k: get(row, k) for k in hmap}
                if rec.get("櫃台審核", "").lower() == "n":
                    rec["預約狀態"] = "已拒絕"
                    rec["訂單狀態"] = "已拒絕"
                results.append(rec)

            return results

        # ===== 修改 =====
        elif action == "modify":
            p = ModifyPayload(**data)
            target = _find_rows_by_pred(ws, lambda r: r.get("預約編號") == p.booking_id)
            if not target:
                raise HTTPException(404, "找不到此預約編號")
            rowno = target[0]

            def get_cell(col: str) -> str:
                if col not in hmap:
                    return ""
                return ws.cell(rowno, hmap[col]).value or ""

            # 目標值（若未給則取舊值）
            new_direction = p.direction or get_cell("往返")
            new_date = _norm_date(p.date or get_cell("日期"))
            time_hm = _time_hm_from_any(p.time or get_cell("班次"))
            new_pick = p.pickLocation or get_cell("上車地點")
            new_drop = p.dropLocation or get_cell("下車地點")
            try:
                old_pax = int(get_cell("預約人數") or "0")
            except:
                old_pax = 0
            new_pax = int(p.passengers if p.passengers is not None else old_pax)

            # ★ 修改時再次檢查容量（同班次可含本人）
            _check_capacity_for_modify(ws, hmap, rowno, new_direction, new_date, time_hm, new_pick, new_drop, new_pax)

            car_display = _display_trip_str(new_date, time_hm)
            pk_idx, dp_idx, seg_str = _compute_indices_and_segments(new_pick, new_drop)

            def upd(col: str, v: Optional[str]):
                if v is None:
                    return
                if col in hmap:
                    ws.update_cell(rowno, hmap[col], v)

            # 寫入更新欄位（★ 需求 10）
            upd("預約狀態", BOOKED_TEXT)
            upd("訂單狀態", BOOKED_TEXT)
            upd("往返", new_direction)
            upd("日期", new_date)
            upd("班次", time_hm)
            upd("車次", car_display)
            upd("上車地點", new_pick)
            upd("下車地點", new_drop)
            upd("預約人數", str(new_pax))
            if p.phone:
                upd("手機", p.phone)
            if p.email:
                upd("信箱", p.email)
                # 依新 email 重算 QR
                em6 = _email_hash6(p.email)
                qr_content = f"FT:{p.booking_id}:{em6}"
                upd("QRCode編碼", qr_content)
            upd("上車索引", str(pk_idx))
            upd("下車索引", str(dp_idx))
            upd("涉及路段範圍", seg_str)
            # 備註寫入「當下修改時間 已修改」
            if "備註" in hmap:
                ws.update_cell(rowno, hmap["備註"], _tz_now_str() + " 已修改")
            if "最後操作時間" in hmap:
                ws.update_cell(rowno, hmap["最後操作時間"], _tz_now_str() + " 已修改")

            return {"status": "success", "booking_id": p.booking_id}

        # ===== 刪除（取消）=====
        elif action == "delete":
            p = DeletePayload(**data)
            target = _find_rows_by_pred(ws, lambda r: r.get("預約編號") == p.booking_id)
            if not target:
                raise HTTPException(404, "找不到此預約編號")
            rowno = target[0]
            if "預約狀態" in hmap:
                ws.update_cell(rowno, hmap["預約狀態"], CANCELLED_TEXT)
            if "訂單狀態" in hmap:
                ws.update_cell(rowno, hmap["訂單狀態"], CANCELLED_TEXT)
            if "備註" in hmap:
                ws.update_cell(rowno, hmap["備註"], _tz_now_str() + " 已刪除")
            if "最後操作時間" in hmap:
                ws.update_cell(rowno, hmap["最後操作時間"], _tz_now_str() + " 已刪除")
            return {"status": "success", "booking_id": p.booking_id}

        # ===== 掃碼上車 =====
        elif action == "check_in":
            p = CheckInPayload(**data)
            if not (p.code or p.booking_id):
                raise HTTPException(400, "需提供 code 或 booking_id")
            target = _find_rows_by_pred(
                ws,
                lambda r: r.get("QRCode編碼") == p.code or r.get("預約編號") == p.booking_id,
            )
            if not target:
                raise HTTPException(404, "找不到符合條件之訂單")
            rowno = target[0]
            if "乘車狀態" in hmap:
                ws.update_cell(rowno, hmap["乘車狀態"], "已上車")
            if "最後操作時間" in hmap:
                ws.update_cell(rowno, hmap["最後操作時間"], _tz_now_str() + " 已上車")
            return {"status": "success", "row": rowno}

        else:
            raise HTTPException(400, f"未知 action：{action}")

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"伺服器錯誤: {str(e)}")

@app.get("/cors_debug")
def cors_debug():
    return {"status": "ok", "cors_test": True, "time": _tz_now_str()}

@app.get("/api/debug")
def debug_endpoint():
    return {"status": "服務正常", "base_url": BASE_URL, "time": _tz_now_str()}
