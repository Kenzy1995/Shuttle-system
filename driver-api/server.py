from __future__ import annotations
import os
import time
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

import google.auth
import gspread
from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel

# ========= Google Sheets 設定 =========

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

# 和你 booking-manager 一樣的 Spreadsheet
SPREADSHEET_ID = "1xp54tKOczklmT8uacW-HMxwV8r0VOR2ui33jYcE2pUQ"
SHEET_NAME_MAIN = "預約審核(櫃台)"
HEADER_ROW_MAIN = 2

# 狀態文字（和原本保持一致）
BOOKED_TEXT = "✔️ 已預約 Booked"
CANCELLED_TEXT = "❌ 已取消 Cancelled"


# ========= 工具函數 =========

def _tz_now_str() -> str:
    """回傳台北時間的現在時間字串。"""
    os.environ.setdefault("TZ", "Asia/Taipei")
    try:
        time.tzset()
    except Exception:
        pass
    t = time.localtime()
    return f"{t.tm_year:04d}-{t.tm_mon:02d}-{t.tm_mday:02d} {t.tm_hour:02d}:{t.tm_min:02d}:{t.tm_sec:02d}"


def _time_hm_from_any(s: str) -> str:
    """把 '18:30', '2025/12/08 18:30', '18：30' 之類的文字整理成 'HH:MM'。"""
    s = (s or "").strip().replace("：", ":")
    if " " in s and ":" in s:
        return s.split()[-1][:5]
    if ":" in s:
        return s[:5]
    return s


def open_ws(name: str) -> gspread.Worksheet:
    credentials, _ = google.auth.default(scopes=SCOPES)
    gc = gspread.authorize(credentials)
    sh = gc.open_by_key(SPREADSHEET_ID)
    return sh.worksheet(name)


def _sheet_headers(ws: gspread.Worksheet, header_row: int) -> List[str]:
    headers = ws.row_values(header_row)
    return [h.strip() for h in headers]


def header_map_main(ws: gspread.Worksheet) -> Dict[str, int]:
    """
    把表頭欄位名稱 -> 欄位位置（1-based index）
    """
    row = _sheet_headers(ws, HEADER_ROW_MAIN)
    m: Dict[str, int] = {}
    for idx, name in enumerate(row, start=1):
        name = (name or "").strip()
        if name and name not in m:
            m[name] = idx
    return m


def _read_all_rows(ws: gspread.Worksheet) -> List[List[str]]:
    return ws.get_all_values()


# ========= Pydantic Models =========

class DriverTrip(BaseModel):
    trip_id: str   # 直接用「車次-日期時間」欄位，例如 "2025/12/08 18:30"
    date: str      # "2025-12-08"
    time: str      # "18:30"
    total_pax: int


class DriverPassenger(BaseModel):
    trip_id: str
    station: str       # 站點名稱
    updown: str        # "上車" / "下車"
    booking_id: str
    name: str
    phone: str
    room: str
    pax: int
    status: str        # "已上車" 或 ""
    qrcode: str        # QRCode 編碼內容


class DriverCheckinRequest(BaseModel):
    qrcode: str


class DriverCheckinResponse(BaseModel):
    status: str
    message: str
    booking_id: Optional[str] = None
    name: Optional[str] = None
    pax: Optional[int] = None
    station: Optional[str] = None


# ========= FastAPI App =========

app = FastAPI(title="Shuttle Driver API", version="1.0.0")


@app.get("/health")
def health():
    return {"status": "ok", "time": _tz_now_str()}


# ========= 1. 取得班次列表 =========

@app.get("/api/driver/trips", response_model=List[DriverTrip])
def driver_get_trips():
    """
    司機用：取得未來班次清單（依日期 + 時間）。
    來源：主表的「車次-日期時間」欄位。
    """
    ws_main = open_ws(SHEET_NAME_MAIN)
    hmap = header_map_main(ws_main)
    values = _read_all_rows(ws_main)

    if not values or "車次-日期時間" not in hmap:
        return []

    idx_car_dt = hmap["車次-日期時間"] - 1
    idx_pax_col = hmap.get("確認人數", hmap.get("預約人數", 0))
    idx_pax = idx_pax_col - 1 if idx_pax_col else None
    idx_status_col = hmap.get("預約狀態")
    idx_status = idx_status_col - 1 if idx_status_col else None

    trips: Dict[str, DriverTrip] = {}

    for row in values[HEADER_ROW_MAIN:]:
        if not any(row):
            continue
        if idx_car_dt >= len(row):
            continue

        car_dt = (row[idx_car_dt] or "").strip()
        if not car_dt:
            continue

        # 跳過已取消
        if idx_status is not None and idx_status < len(row):
            st = (row[idx_status] or "").strip()
            if st == CANCELLED_TEXT:
                continue

        # car_dt 例如 "2025/12/08 18:30"
        try:
            parts = car_dt.split()
            date_str = parts[0].replace("/", "-")    # 轉成 "YYYY-MM-DD"
            time_str = _time_hm_from_any(parts[1] if len(parts) > 1 else "")
        except Exception:
            continue

        # 只取「今天 -1 日」之後的班次（避免太舊）
        try:
            dt = datetime.strptime(date_str, "%Y-%m-%d")
            if dt < datetime.today() - timedelta(days=1):
                continue
        except Exception:
            pass

        key = car_dt  # 當作 trip_id

        if key not in trips:
            trips[key] = DriverTrip(
                trip_id=key,
                date=date_str,
                time=time_str,
                total_pax=0,
            )

        if idx_pax is not None and idx_pax < len(row):
            try:
                p = int((row[idx_pax] or "0").strip() or "0")
            except Exception:
                p = 0
            trips[key].total_pax += p

    # 依日期 + 時間排序
    return sorted(trips.values(), key=lambda t: (t.date, t.time))


# ========= 2. 取得某班次乘客清單 =========

@app.get("/api/driver/trip_passengers", response_model=List[DriverPassenger])
def driver_get_trip_passengers(
    trip_id: str = Query(..., description="車次-日期時間，例如 2025/12/08 18:30")
):
    """
    司機用：取得指定班次的乘客清單。
    每位乘客會拆成「上車」與「下車」兩筆（如果有設定）。
    """
    ws_main = open_ws(SHEET_NAME_MAIN)
    hmap = header_map_main(ws_main)
    values = _read_all_rows(ws_main)

    if not values or "車次-日期時間" not in hmap:
        return []

    idx_car_dt = hmap["車次-日期時間"] - 1

    idx_booking = hmap.get("預約編號", 0) - 1
    idx_name = hmap.get("姓名", 0) - 1
    idx_phone = hmap.get("手機", 0) - 1
    idx_room = hmap.get("房號", 0) - 1
    idx_pax_col = hmap.get("確認人數", hmap.get("預約人數", 0))
    idx_pax = idx_pax_col - 1 if idx_pax_col else None
    idx_pick = hmap.get("上車地點", 0) - 1
    idx_drop = hmap.get("下車地點", 0) - 1
    idx_status = hmap.get("乘車狀態", 0) - 1
    idx_qr = hmap.get("QRCode編碼", 0) - 1

    result: List[DriverPassenger] = []

    for row in values[HEADER_ROW_MAIN:]:
        if not any(row):
            continue
        if idx_car_dt >= len(row):
            continue
        car_dt = (row[idx_car_dt] or "").strip()
        if car_dt != trip_id:
            continue

        booking_id = (row[idx_booking] if 0 <= idx_booking < len(row) else "").strip()
        name = (row[idx_name] if 0 <= idx_name < len(row) else "").strip()
        phone = (row[idx_phone] if 0 <= idx_phone < len(row) else "").strip()
        room = (row[idx_room] if 0 <= idx_room < len(row) else "").strip()
        status = (row[idx_status] if 0 <= idx_status < len(row) else "").strip()
        qrcode = (row[idx_qr] if 0 <= idx_qr < len(row) else "").strip()

        if idx_pax is not None and 0 <= idx_pax < len(row):
            try:
                pax = int((row[idx_pax] or "1").strip() or "1")
            except Exception:
                pax = 1
        else:
            pax = 1

        pick = (row[idx_pick] if 0 <= idx_pick < len(row) else "").strip()
        drop = (row[idx_drop] if 0 <= idx_drop < len(row) else "").strip()

        # 上車
        if pick:
            result.append(
                DriverPassenger(
                    trip_id=trip_id,
                    station=pick,
                    updown="上車",
                    booking_id=booking_id,
                    name=name,
                    phone=phone,
                    room=room,
                    pax=pax,
                    status=status,
                    qrcode=qrcode,
                )
            )
        # 下車
        if drop:
            result.append(
                DriverPassenger(
                    trip_id=trip_id,
                    station=drop,
                    updown="下車",
                    booking_id=booking_id,
                    name=name,
                    phone=phone,
                    room=room,
                    pax=pax,
                    status=status,
                    qrcode=qrcode,
                )
            )

    # 依「站點 → 上/下 → 預約編號」排序
    def sort_key(p: DriverPassenger):
        return (p.station, 0 if p.updown == "上車" else 1, p.booking_id)

    return sorted(result, key=sort_key)


# ========= 3. 掃描 QRCode → 更新乘車狀態 =========

@app.post("/api/driver/checkin", response_model=DriverCheckinResponse)
def driver_checkin(req: DriverCheckinRequest):
    """
    司機用：掃描 QRCode 後，將該訂單標記為「已上車」。
    QR 格式：FT:{booking_id}:{hash}
    """
    code = (req.qrcode or "").strip()
    if not code:
        raise HTTPException(400, "缺少 qrcode")

    parts = code.split(":")
    if len(parts) < 3 or parts[0] != "FT":
        return DriverCheckinResponse(
            status="error",
            message="QRCode 格式錯誤",
        )
    booking_id = parts[1]

    ws_main = open_ws(SHEET_NAME_MAIN)
    hmap = header_map_main(ws_main)
    values = _read_all_rows(ws_main)

    if "預約編號" not in hmap:
        raise HTTPException(500, "主表缺少『預約編號』欄位")

    col_booking = hmap["預約編號"]
    rowno: Optional[int] = None

    # 從主表找到該 booking 的列號（1-based）
    for i, row in enumerate(values[HEADER_ROW_MAIN:], start=HEADER_ROW_MAIN + 1):
        if col_booking - 1 < len(row):
            if (row[col_booking - 1] or "").strip() == booking_id:
                rowno = i
                break

    if rowno is None:
        return DriverCheckinResponse(
            status="not_found",
            message=f"找不到預約編號 {booking_id}",
        )

    def getv(col: str) -> str:
        if col not in hmap:
            return ""
        return ws_main.cell(rowno, hmap[col]).value or ""

    # 更新「乘車狀態」與「最後操作時間」
    updates: Dict[str, str] = {}
    if "乘車狀態" in hmap:
        updates["乘車狀態"] = "已上車"
    if "最後操作時間" in hmap:
        updates["最後操作時間"] = _tz_now_str() + " 已上車(司機)"

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

    # 回傳給前端顯示
    try:
        pax = int((getv("確認人數") or getv("預約人數") or "1"))
    except Exception:
        pax = 1

    return DriverCheckinResponse(
        status="success",
        message="已完成上車紀錄",
        booking_id=booking_id,
        name=getv("姓名"),
        pax=pax,
        station=getv("上車地點"),
    )
