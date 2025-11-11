from __future__ import annotations
import io
import os
import time
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional
import urllib.parse

import qrcode
from fastapi import FastAPI, HTTPException, Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, validator
import gspread
import google.auth
import hashlib
from gspread.utils import rowcol_to_a1

# ========== 常數與工具 ==========
SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]
SPREADSHEET_ID = "1xp54tKOczklmT8uacW-HMxwV8r0VOR2ui33jYcE2pUQ"
SHEET_NAME = "預約審核(櫃台)"
BASE_URL = "https://booking-manager-995728097341.asia-east1.run.app"

# 表頭列（1-based）
HEADER_ROW = 2

# 狀態固定字串
BOOKED_TEXT = "✔️ 已預約 Booked"
CANCELLED_TEXT = "❌ 已取消 Cancelled"

# 僅允許精準欄位名稱
HEADER_KEYS = {
    "申請日期","最後操作時間","預約編號","往返","日期","班次","車次",
    "上車地點","下車地點","姓名","手機","信箱","預約人數","櫃台審核","預約狀態","乘車狀態",
    "身分","房號","入住日期","退房日期","用餐日期","上車索引","下車索引","涉及路段範圍","QRCode編碼","備註"
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

def _row_a1(ws: gspread.Worksheet, rowno: int) -> str:
    """回傳 A{row}:<lastcol>{row} 的 A1 範圍"""
    last_col = len(_sheet_headers(ws))
    start = rowcol_to_a1(rowno, 1)
    end = rowcol_to_a1(rowno, last_col)
    return f"{start}:{end}"

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

class DeletePayload(BaseModel):
    booking_id: str

class CheckInPayload(BaseModel):
    code: Optional[str] = None
    booking_id: Optional[str] = None

class OpsRequest(BaseModel):
    action: str
    data: Dict[str, Any]

# ========== FastAPI ==========
app = FastAPI(title="Shuttle Ops API", version="1.2.0-batch")

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
            last_seq = _get_max_seq_for_date(ws, p.date)
            booking_id = f"{_mmdd_prefix(p.date)}{last_seq + 1:03d}"
            car_display = _display_trip_str(p.date, _time_hm_from_any(p.time))

            pk_idx, dp_idx, seg_str = _compute_indices_and_segments(p.pickLocation, p.dropLocation)

            em6 = _email_hash6(p.email)
            qr_content = f"FT:{booking_id}:{em6}"
            qr_url = f"{BASE_URL}/api/qr/{urllib.parse.quote(qr_content)}"

            newrow = [""] * len(headers)
            setv(newrow, "申請日期", _tz_now_str())
            setv(newrow, "預約狀態", BOOKED_TEXT)
            identity_simple = "住宿" if p.identity == "hotel" else "用餐"

            setv(newrow, "預約編號", booking_id)
            setv(newrow, "往返", p.direction)
            setv(newrow, "日期", p.date)
            setv(newrow, "班次", _time_hm_from_any(p.time))
            setv(newrow, "車次", car_display)
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
                    d = datetime.strptime(date_iso, "%Y-%m-%d")
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
                results.append(rec)

            return results

        # ===== 修改（單次讀取 + 單次覆蓋寫入）=====
        elif action == "modify":
            p = ModifyPayload(**data)
            targets = _find_rows_by_pred(ws, lambda r: r.get("預約編號") == p.booking_id)
            if not targets:
                raise HTTPException(404, "找不到此預約編號")
            rowno = targets[0]

            # 先抓整列
            values_all = _read_all_rows(ws)
            headers_line = values_all[HEADER_ROW - 1]
            current_row = values_all[rowno - 1] if rowno - 1 < len(values_all) else [""] * len(headers_line)
            # 對齊長度
            if len(current_row) < len(headers_line):
                current_row += [""] * (len(headers_line) - len(current_row))

            # 以 dict 處理
            row_dict = {headers_line[i]: (current_row[i] if i < len(current_row) else "") for i in range(len(headers_line))}

            # 計算更新欄位
            if p.direction: row_dict["往返"] = p.direction
            if p.date: row_dict["日期"] = p.date
            time_hm = _time_hm_from_any(p.time or row_dict.get("班次",""))
            if p.time: row_dict["班次"] = time_hm
            if p.date or p.time:
                d = row_dict.get("日期","")
                if d and time_hm:
                    row_dict["車次"] = _display_trip_str(d, time_hm)

            if p.pickLocation: row_dict["上車地點"] = p.pickLocation
            if p.dropLocation: row_dict["下車地點"] = p.dropLocation
            if p.phone: row_dict["手機"] = p.phone
            if p.email:
                row_dict["信箱"] = p.email
                em6 = _email_hash6(p.email)
                row_dict["QRCode編碼"] = f"FT:{p.booking_id}:{em6}"
            if p.passengers is not None:
                row_dict["預約人數"] = str(p.passengers)

            # 路段與索引
            if row_dict.get("上車地點") and row_dict.get("下車地點"):
                pk_idx, dp_idx, seg_str = _compute_indices_and_segments(row_dict["上車地點"], row_dict["下車地點"])
                row_dict["上車索引"] = str(pk_idx)
                row_dict["下車索引"] = str(dp_idx)
                row_dict["涉及路段範圍"] = seg_str

            # 覆蓋狀態與最後時間
            row_dict["預約狀態"] = BOOKED_TEXT
            row_dict["最後操作時間"] = _tz_now_str() + " 已修改"
            note = (row_dict.get("備註") or "").strip()
            row_dict["備註"] = (note + "; " if note else "") + _tz_now_str() + " 已修改"

            # 轉回列陣列
            new_row = [row_dict.get(h, "") for h in headers_line]

            # 單次覆蓋寫入
            a1 = _row_a1(ws, rowno)
            ws.update(a1, [new_row], value_input_option="USER_ENTERED")

            return {"status": "success", "booking_id": p.booking_id}

        # ===== 刪除（單次讀取 + 單次覆蓋寫入）=====
        elif action == "delete":
            p = DeletePayload(**data)
            targets = _find_rows_by_pred(ws, lambda r: r.get("預約編號") == p.booking_id)
            if not targets:
                raise HTTPException(404, "找不到此預約編號")
            rowno = targets[0]

            values_all = _read_all_rows(ws)
            headers_line = values_all[HEADER_ROW - 1]
            current_row = values_all[rowno - 1] if rowno - 1 < len(values_all) else [""] * len(headers_line)
            if len(current_row) < len(headers_line):
                current_row += [""] * (len(headers_line) - len(current_row))

            row_dict = {headers_line[i]: (current_row[i] if i < len(current_row) else "") for i in range(len(headers_line))}
            row_dict["預約狀態"] = CANCELLED_TEXT
            row_dict["最後操作時間"] = _tz_now_str() + " 已刪除"
            note = (row_dict.get("備註") or "").strip()
            row_dict["備註"] = (note + "; " if note else "") + _tz_now_str() + " 已取消"

            new_row = [row_dict.get(h, "") for h in headers_line]
            a1 = _row_a1(ws, rowno)
            ws.update(a1, [new_row], value_input_option="USER_ENTERED")
            return {"status": "success", "booking_id": p.booking_id}

        # ===== 掃碼上車 =====
        elif action == "check_in":
            p = CheckInPayload(**data)
            if not (p.code or p.booking_id):
                raise HTTPException(400, "需提供 code 或 booking_id")
            targets = _find_rows_by_pred(ws, lambda r: r.get("QRCode編碼") == p.code or r.get("預約編號") == p.booking_id)
            if not targets:
                raise HTTPException(404, "找不到符合條件之訂單")
            rowno = targets[0]

            values_all = _read_all_rows(ws)
            headers_line = values_all[HEADER_ROW - 1]
            current_row = values_all[rowno - 1] if rowno - 1 < len(values_all) else [""] * len(headers_line)
            if len(current_row) < len(headers_line):
                current_row += [""] * (len(headers_line) - len(current_row))

            row_dict = {headers_line[i]: (current_row[i] if i < len(current_row) else "") for i in range(len(headers_line))}
            row_dict["乘車狀態"] = "已上車"
            row_dict["最後操作時間"] = _tz_now_str() + " 已上車"
            new_row = [row_dict.get(h, "") for h in headers_line]
            a1 = _row_a1(ws, rowno)
            ws.update(a1, [new_row], value_input_option="USER_ENTERED")
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
