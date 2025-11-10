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


# ========== 常數與工具 ==========
SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]
SPREADSHEET_ID = "1xp54tKOczklmT8uacW-HMxwV8r0VOR2ui33jYcE2pUQ"
SHEET_NAME = "預約審核(櫃台)"
BASE_URL = "https://booking-manager-995728097341.asia-east1.run.app"

# 表頭實際位於第幾列（1-based）
HEADER_ROW = 2

# 狀態固定字串
BOOKED_TEXT = "✔️ 已預約 Booked"
CANCELLED_TEXT = "❌ 已取消 Cancelled"

# 統一欄位名稱映射
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

# 上車/下車索引查表（不需判斷方向）
PICK_INDEX_MAP = {
    "福泰大飯店": 1,
    "南港展覽館-捷運3號出口": 2,
    "南港火車站": 3,
    "南港 LaLaport Shopping Park": 4,
}
DROP_INDEX_MAP = {
    "南港展覽館-捷運3號出口": 2,
    "南港火車站": 3,
    "南港 LaLaport Shopping Park": 4,
    "福泰大飯店": 5,
}


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
    # yyyy/m/d HH:MM（月份與日期不補零，時分補零）
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
    # 顯示車次避免被當作日期，自行前置單引號
    y, m, d = date_iso.split("-")
    return f"'%s/%s %s" % (int(m), int(d), time_hm)


def _mmdd_prefix(date_iso: str) -> str:
    y, m, d = date_iso.split("-")
    return f"{int(m):02d}{int(d):02d}"


def _compute_indices_and_segments(pickup: str, dropoff: str):
    """
    直接查表：
      上車索引：飯店=1, 捷運站=2, 火車站=3, LaLaport=4
      下車索引：捷運站=2, 火車站=3, LaLaport=4, 飯店=5
    涉及路段範圍 = [上車索引, 下車索引)（不含下車索引）
    """
    p = _normalize_stop(pickup)
    d = _normalize_stop(dropoff)

    pick_idx = PICK_INDEX_MAP.get(p, 0)
    drop_idx = DROP_INDEX_MAP.get(d, 0)

    if pick_idx == 0 or drop_idx == 0 or drop_idx <= pick_idx:
        return pick_idx, drop_idx, ""

    segs = ",".join(str(i) for i in range(pick_idx, drop_idx))
    return pick_idx, drop_idx, segs


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
    headers = values[HEADER_ROW - 1] if len(values) >= HEADER_ROW else []
    result = []
    for i, row in enumerate(values[HEADER_ROW:], start=HEADER_ROW + 1):
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


class DeletePayload(BaseModel):
    booking_id: str


class CheckInPayload(BaseModel):
    code: Optional[str] = None
    booking_id: Optional[str] = None


class OpsRequest(BaseModel):
    action: str
    data: Dict[str, Any]


# ========== FastAPI ==========
app = FastAPI(title="Shuttle Ops API", version="1.0.5")

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
            pk_idx, dp_idx, seg_str = _compute_indices_and_segments(
                p.pickLocation, p.dropLocation
            )

            qr_content = f"FORTEXZ:{booking_id}"
            qr_url = f"{BASE_URL}/api/qr/{urllib.parse.quote(qr_content)}"

            newrow = [""] * len(headers)

            # 申請日期（文字形式 yyyy/m/d HH:MM 由 USER_ENTERED 判定）
            setv(newrow, "申請日期", _tz_now_str())

            # 預約狀態
            setv(newrow, "預約狀態", BOOKED_TEXT)

            # 身分：住宿 / 用餐
            identity_simple = "住宿" if p.identity == "hotel" else "用餐"

            # 其他欄位
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

            # 索引與範圍（不含下車索引）
            setv(newrow, "上車索引", pk_idx)
            setv(newrow, "下車索引", dp_idx)
            setv(newrow, "涉及路段範圍", seg_str)

            # QR 編碼
            setv(newrow, "QRCode編碼", qr_content)

            ws.append_row(newrow, value_input_option="USER_ENTERED")

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
                if rec.get("櫃台審核", "") == "n":
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
            if "預約狀態" in hmap:
                ws.update_cell(rowno, hmap["預約狀態"], BOOKED_TEXT)
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
