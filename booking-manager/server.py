from __future__ import annotations
import io
import os
import time
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional
import urllib.parse
import logging

import qrcode
from fastapi import FastAPI, HTTPException, Response, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, validator
import gspread
import google.auth
import hashlib

# ========== 日誌 ==========
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s %(levelname)s %(message)s",
)
log = logging.getLogger("booking-manager")

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
    "寄信狀態",  # 仍保留欄位，但不寄信，只寫入狀態
}

# 站點索引（精準雙語）
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
    if not date_iso or not time_hm:
        return ""
    y, m, d = date_iso.split("-")
    return f"'{int(m)}/{int(d)} {time_hm}"

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
        log.exception("open_sheet 失敗")
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

class MailPayload(BaseModel):
    booking_id: str
    lang: str = Field("zh", pattern="^(zh|en|ja|ko)$")
    kind: str = Field(..., pattern="^(book|modify|cancel)$")
    ticket_png_base64: Optional[str] = None

class OpsRequest(BaseModel):
    action: str
    data: Dict[str, Any]

# ========== FastAPI ==========
app = FastAPI(title="Shuttle Ops API", version="1.2.1")

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

@app.middleware("http")
async def log_requests(request: Request, call_next):
    try:
        body = await request.body()
    except Exception:
        body = b""
    log.debug("REQ %s %s body=%s", request.method, request.url.path, body[:2048])
    resp = await call_next(request)
    log.debug("RES %s %s status=%s", request.method, request.url.path, resp.status_code)
    return resp

# 健康檢查
@app.get("/health")
def health():
    return {"status": "ok", "time": _tz_now_str()}

# QR 影像
@app.get("/api/qr/{code}")
def qr_image(code: str):
    try:
        decoded_code = urllib.parse.unquote(code)
        img = qrcode.make(decoded_code)
        bio = io.BytesIO()
        img.save(bio, format="PNG")
        return Response(content=bio.getvalue(), media_type="image/png")
    except Exception as e:
        log.exception("QR 生成失敗")
        raise HTTPException(500, f"QR 生成失敗: {str(e)}")

# ========== 主 API ==========
# 允許預檢請求
@app.options("/api/ops")
@app.options("/api/ops/")
def ops_options():
    return Response(status_code=204)

# 同一路徑支援有無尾斜線
@app.post("/api/ops")
@app.post("/api/ops/")
def ops(req: OpsRequest):
    action = (req.action or "").strip().lower()
    data = req.data or {}
    log.debug("ops action=%s data=%s", action, data)

    try:
        ws = open_sheet()
        hmap = header_map(ws)
        headers = _sheet_headers(ws)
        log.debug("headers map=%s", hmap)

        def setv(row_arr: List[str], col: str, v: Any):
            if col in hmap and 1 <= hmap[col] <= len(row_arr):
                row_arr[hmap[col] - 1] = v if isinstance(v, str) else str(v)

        def get_by_rowno(rowno: int, key: str) -> str:
            if key not in hmap:
                return ""
            return ws.cell(rowno, hmap[key]).value or ""

        def _assert_required_headers(required_cols: List[str]):
            missing = [c for c in required_cols if c not in hmap]
            if missing:
                raise HTTPException(
                    500,
                    f"試算表缺少必要欄位或 HEADER_ROW 錯誤：{missing}"
                )

        REQUIRED_FOR_BOOK = [
            "申請日期","預約狀態","預約編號","往返","日期","班次","車次",
            "上車地點","下車地點","姓名","手機","信箱","預約人數","QRCode編碼"
        ]

        # ===== 新增預約 =====
        if action == "book":
            p = BookPayload(**data)
            _assert_required_headers(REQUIRED_FOR_BOOK)

            # 先計算預約編號，但不回傳給前端，直到 append_row 成功
            last_seq = _get_max_seq_for_date(ws, p.date)
            booking_id = f"{_mmdd_prefix(p.date)}{last_seq + 1:03d}"
            time_hm = _time_hm_from_any(p.time)
            car_display = _display_trip_str(p.date, time_hm)
            pk_idx, dp_idx, seg_str = _compute_indices_and_segments(p.pickLocation, p.dropLocation)
            em6 = _email_hash6(p.email)
            qr_content = f"FT:{booking_id}:{em6}"
            qr_url = f"{BASE_URL}/api/qr/{urllib.parse.quote(qr_content)}"

            # 一次性組裝整列。只寫入一次，避免欄位錯位。
            newrow = [""] * len(headers)
            setv(newrow, "申請日期", _tz_now_str())
            setv(newrow, "預約狀態", BOOKED_TEXT)
            setv(newrow, "預約編號", booking_id)
            setv(newrow, "往返", p.direction)
            setv(newrow, "日期", p.date)
            setv(newrow, "班次", time_hm)
            setv(newrow, "車次", car_display)
            setv(newrow, "上車地點", p.pickLocation)
            setv(newrow, "下車地點", p.dropLocation)
            setv(newrow, "姓名", p.name)
            setv(newrow, "手機", p.phone)
            setv(newrow, "信箱", p.email)
            setv(newrow, "預約人數", p.passengers)
            setv(newrow, "乘車狀態", "")
            setv(newrow, "身分", "住宿" if p.identity == "hotel" else "用餐")
            setv(newrow, "房號", p.roomNumber or "")
            setv(newrow, "入住日期", p.checkIn or "")
            setv(newrow, "退房日期", p.checkOut or "")
            setv(newrow, "用餐日期", p.diningDate or "")
            setv(newrow, "上車索引", pk_idx)
            setv(newrow, "下車索引", dp_idx)
            setv(newrow, "涉及路段範圍", seg_str)
            setv(newrow, "QRCode編碼", qr_content)
            # 寄信狀態先標記為「已跳過」
            if "寄信狀態" in hmap:
                setv(newrow, "寄信狀態", f"{_tz_now_str()} 已跳過寄信")

            log.debug("append_row payload=%s", newrow)
            ws.append_row(newrow, value_input_option="USER_ENTERED")
            log.info("append_row 成功 booking_id=%s", booking_id)

            # 成功寫入後才回傳
            return {
                "status": "success",
                "booking_id": booking_id,
                "qr_url": qr_url,
                "qr_content": qr_content,
            }

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

        # ===== 修改 =====
        elif action == "modify":
            p = ModifyPayload(**data)
            target = _find_rows_by_pred(ws, lambda r: r.get("預約編號") == p.booking_id)
            if not target:
                raise HTTPException(404, "找不到此預約編號")
            rowno = target[0]

            updates = {}

            time_hm = _time_hm_from_any(p.time or "")
            car_display = _display_trip_str(p.date or "", time_hm) if (p.date and time_hm) else None

            pk_idx = dp_idx = None
            seg_str = None
            if p.pickLocation and p.dropLocation:
                pk_idx, dp_idx, seg_str = _compute_indices_and_segments(p.pickLocation, p.dropLocation)

            updates["預約狀態"] = BOOKED_TEXT
            if p.passengers is not None:
                updates["預約人數"] = str(p.passengers)

            if "備註" in hmap:
                current_note = ws.cell(rowno, hmap["備註"]).value or ""
                new_note = f"{_tz_now_str()} 已修改"
                if current_note:
                    new_note = f"{current_note}; {new_note}"
                updates["備註"] = new_note

            if p.direction: updates["往返"] = p.direction
            if p.date: updates["日期"] = p.date
            if time_hm: updates["班次"] = time_hm
            if car_display: updates["車次"] = car_display
            if p.pickLocation: updates["上車地點"] = p.pickLocation
            if p.dropLocation: updates["下車地點"] = p.dropLocation
            if p.phone: updates["手機"] = p.phone
            if p.email:
                updates["信箱"] = p.email
                em6 = _email_hash6(p.email)
                updates["QRCode編碼"] = f"FT:{p.booking_id}:{em6}"
            if pk_idx is not None: updates["上車索引"] = str(pk_idx)
            if dp_idx is not None: updates["下車索引"] = str(dp_idx)
            if seg_str is not None: updates["涉及路段範圍"] = seg_str
            if "最後操作時間" in hmap:
                updates["最後操作時間"] = _tz_now_str() + " 已修改"

            if updates:
                batch_updates = []
                for col_name, value in updates.items():
                    if col_name in hmap:
                        batch_updates.append({
                            'range': gspread.utils.rowcol_to_a1(rowno, hmap[col_name]),
                            'values': [[value]]
                        })
                if batch_updates:
                    log.debug("modify batch_updates=%s", batch_updates)
                    ws.batch_update(batch_updates)

            return {"status": "success", "booking_id": p.booking_id}

        # ===== 刪除（取消）=====
        elif action == "delete":
            p = DeletePayload(**data)
            target = _find_rows_by_pred(ws, lambda r: r.get("預約編號") == p.booking_id)
            if not target:
                raise HTTPException(404, "找不到此預約編號")
            rowno = target[0]

            updates = {}
            if "預約狀態" in hmap:
                updates["預約狀態"] = CANCELLED_TEXT
            if "備註" in hmap:
                current_note = ws.cell(rowno, hmap["備註"]).value or ""
                new_note = f"{_tz_now_str()} 已取消"
                if current_note:
                    new_note = f"{current_note}; {new_note}"
                updates["備註"] = new_note
            if "最後操作時間" in hmap:
                updates["最後操作時間"] = _tz_now_str() + " 已刪除"

            if updates:
                batch_updates = []
                for col_name, value in updates.items():
                    if col_name in hmap:
                        batch_updates.append({
                            'range': gspread.utils.rowcol_to_a1(rowno, hmap[col_name]),
                            'values': [[value]]
                        })
                if batch_updates:
                    log.debug("delete batch_updates=%s", batch_updates)
                    ws.batch_update(batch_updates)

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

            updates = {}
            if "乘車狀態" in hmap:
                updates["乘車狀態"] = "已上車"
            if "最後操作時間" in hmap:
                updates["最後操作時間"] = _tz_now_str() + " 已上車"

            if updates:
                batch_updates = []
                for col_name, value in updates.items():
                    if col_name in hmap:
                        batch_updates.append({
                            'range': gspread.utils.rowcol_to_a1(rowno, hmap[col_name]),
                            'values': [[value]]
                        })
                if batch_updates:
                    log.debug("check_in batch_updates=%s", batch_updates)
                    ws.batch_update(batch_updates)

            return {"status": "success", "row": rowno}

        # ===== 寄信：暫停，僅登記狀態 =====
        elif action == "mail":
            p = MailPayload(**data)
            target = _find_rows_by_pred(ws, lambda r: r.get("預約編號") == p.booking_id)
            if not target:
                raise HTTPException(404, "找不到此預約編號")
            rowno = target[0]

            status_text = f"{_tz_now_str()} 已跳過寄信"
            if "寄信狀態" in hmap:
                a1 = gspread.utils.rowcol_to_a1(rowno, hmap["寄信狀態"])
                ws.update_acell(a1, status_text)
            return {"status": "mail_skipped", "booking_id": p.booking_id, "mail_note": status_text}

        else:
            raise HTTPException(400, f"未知 action：{action}")

    except HTTPException:
        raise
    except Exception as e:
        log.exception("ops 內部錯誤")
        raise HTTPException(500, f"伺服器錯誤: {str(e)}")

# CORS debug
@app.get("/cors_debug")
def cors_debug():
    return {"status": "ok", "cors_test": True, "time": _tz_now_str()}

@app.get("/api/debug")
def debug_endpoint():
    return {"status": "服務正常", "base_url": BASE_URL, "time": _tz_now_str()}
