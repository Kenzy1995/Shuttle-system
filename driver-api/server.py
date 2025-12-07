from __future__ import annotations
import os
import time
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

import google.auth
import gspread
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# ========= Google Sheets 設定 =========

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

SPREADSHEET_ID = "1xp54tKOczklmT8uacW-HMxwV8r0VOR2ui33jYcE2pUQ"
SHEET_NAME_MAIN = "預約審核(櫃台)"
HEADER_ROW_MAIN = 2  # 第二列是表頭

BOOKED_TEXT = "✔️ 已預約 Booked"
CANCELLED_TEXT = "❌ 已取消 Cancelled"

# 站點（必須和主表內容一致）
HOTEL = "福泰大飯店 Forte Hotel"
MRT = "南港展覽館捷運站 Nangang Exhibition Center - MRT Exit 3"
TRAIN = "南港火車站 Nangang Train Station"
MALL = "LaLaport Shopping Park"


# ========= 工具函數 =========

def _tz_now_str() -> str:
    """台北時間現在的文字（yyyy-MM-dd HH:mm:ss）"""
    os.environ.setdefault("TZ", "Asia/Taipei")
    try:
        time.tzset()
    except Exception:
        pass
    t = time.localtime()
    return f"{t.tm_year:04d}-{t.tm_mon:02d}-{t.tm_mday:02d} {t.tm_hour:02d}:{t.tm_min:02d}:{t.tm_sec:02d}"


def _tz_now_dt() -> datetime:
    """台北時間現在的 datetime（naive，但已是台北時區的本地時間）"""
    os.environ.setdefault("TZ", "Asia/Taipei")
    try:
        time.tzset()
    except Exception:
        pass
    t = time.localtime()
    return datetime(t.tm_year, t.tm_mon, t.tm_mday, t.tm_hour, t.tm_min, t.tm_sec)


def _time_hm_from_any(s: str) -> str:
    """
    把 '18:30', '2025/12/08 18:30', '18：30' 等整理成 'HH:MM'
    """
    s = (s or "").strip().replace("：", ":")
    if " " in s and ":" in s:
        return s.split()[-1][:5]
    if ":" in s:
        return s[:5]
    return s


def _parse_main_dt(s: str) -> Tuple[str, str, Optional[datetime]]:
    """
    將主班次時間字串拆成 (日期yyyy-MM-dd, 時間HH:MM, datetime物件或None)
    支援 'YYYY/MM/DD HH:MM' 或 'YYYY-MM-DD HH:MM'
    """
    raw = (s or "").strip()
    if not raw:
        return "", "", None

    txt = raw.replace("年", "-").replace("月", "-").replace("日", " ").replace("/", "-")
    parts = txt.split()
    if not parts:
        return "", "", None
    if len(parts) == 1:
        date_part = parts[0]
        time_part = "00:00"
    else:
        date_part = parts[0]
        time_part = _time_hm_from_any(parts[1])

    date_norm = date_part
    # 盡量補零 (yyyy-m-d → yyyy-mm-dd)
    try:
        y, m, d = date_norm.split("-")
        date_norm = f"{int(y):04d}-{int(m):02d}-{int(d):02d}"
    except Exception:
        pass

    dt = None
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            dt = datetime.strptime(f"{date_norm} {time_part}", "%Y-%m-%d %H:%M")
            break
        except Exception:
            dt = None
    return date_norm, time_part, dt


def open_ws(name: str) -> gspread.Worksheet:
    """開啟指定名稱的工作表"""
    credentials, _ = google.auth.default(scopes=SCOPES)
    gc = gspread.authorize(credentials)
    sh = gc.open_by_key(SPREADSHEET_ID)
    return sh.worksheet(name)


def _sheet_headers(ws: gspread.Worksheet, header_row: int) -> List[str]:
    headers = ws.row_values(header_row)
    return [h.strip() for h in headers]


def header_map_main(ws: gspread.Worksheet) -> Dict[str, int]:
    """
    把表頭欄位名稱 → 欄位位置（1-based index）
    例：{"主班次時間": 19, "預約編號": 3, ...}
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


def _find_booking_row(values: List[List[str]], hmap: Dict[str, int], booking_id: str) -> Optional[int]:
    """在全表裡找到指定 booking_id 的列號（Sheet 的 1-based row）"""
    col = hmap.get("預約編號")
    if not col:
        return None
    col_idx = col - 1
    for i, row in enumerate(values[HEADER_ROW_MAIN:], start=HEADER_ROW_MAIN + 1):
        if col_idx < len(row) and (row[col_idx] or "").strip() == booking_id:
            return i
    return None


def _get_cell_from_row(row: List[str], hmap: Dict[str, int], col_name: str) -> str:
    """從單一 row（list）用欄位名稱取得欄位值"""
    idx = hmap.get(col_name)
    if not idx:
        return ""
    i = idx - 1
    if i >= len(row):
        return ""
    return row[i] or ""


# ========= Pydantic Models =========

class DriverTrip(BaseModel):
    trip_id: str   # 使用「主班次時間」欄位原字串，例如 "2025/12/08 18:30"
    date: str      # "2025-12-08"
    time: str      # "18:30"
    total_pax: int


class DriverPassenger(BaseModel):
    trip_id: str
    main_departure: str   # 主班次時間原字串
    station: str          # 站點名稱
    updown: str           # "上車" / "下車"
    booking_id: str
    name: str
    phone: str
    room: str
    pax: int
    status: str           # "已上車" 或 ""
    qrcode: str
    direction: str = ""   # 往返（去程/回程）
    station_order: int = 99  # 站點排序用（1~5）


class PassengerListRow(BaseModel):
    main_departure: str   # 主班次時間原字串，如 "2025/12/08 17:00"
    main_date: str        # "2025-12-08"
    main_time: str        # "17:00"
    car: str              # 車次（原表「車次」欄）
    booking_id: str
    ride_status: str      # 乘車狀態
    direction: str        # 往返：去程/回程
    name: str
    phone: str
    room: str
    pax: int
    hotel_go: str         # 飯店(去) 欄：上/下/空
    mrt: str              # 捷運站 欄：上/下/空
    train: str            # 火車站 欄：上/下/空
    mall: str             # LaLaport 欄：上/下/空
    hotel_back: str       # 飯店(回) 欄：上/下/空
    station_order: int    # 用於排序（同一方向內站點順序）
    dropoff_order: int    # 用於排序（下車順序）


class DriverCheckinRequest(BaseModel):
    qrcode: str  # 掃到的整段字串：FT:{booking_id}:{hash}


class DriverCheckinResponse(BaseModel):
    status: str
    message: str
    booking_id: Optional[str] = None
    name: Optional[str] = None
    pax: Optional[int] = None
    station: Optional[str] = None


# ========= FastAPI App =========

app = FastAPI(title="Shuttle Driver API", version="2.0.0")

# CORS - 給正式前端用，先全部放行，之後你可改成指定網域
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health():
    return {"status": "ok", "time": _tz_now_str()}


# ========= 1. 取得「預計出車」班次列表（主班次時間） =========

@app.get("/api/driver/trips", response_model=List[DriverTrip])
def driver_get_trips():
    """
    司機用：取得未來班次清單（依「主班次時間」去重）。
    對應你原本的 ARRAYFORMULA（用主班次時間 S 欄、過濾 >= NOW()-1/24）。
    """
    ws_main = open_ws(SHEET_NAME_MAIN)
    hmap = header_map_main(ws_main)
    values = _read_all_rows(ws_main)

    col_main = hmap.get("主班次時間")
    if not values or not col_main:
        return []

    idx_main = col_main - 1
    col_pax = hmap.get("確認人數") or hmap.get("預約人數")
    idx_pax = col_pax - 1 if col_pax else None
    col_status = hmap.get("預約狀態")
    idx_status = col_status - 1 if col_status else None

    trips: Dict[str, DriverTrip] = {}

    now_dt = _tz_now_dt()
    # 對齊你原本公式：主班次時間 >= NOW() - 1/24
    min_dt = now_dt - timedelta(hours=1)

    for row in values[HEADER_ROW_MAIN:]:
        if not any(row):
            continue
        if idx_main >= len(row):
            continue

        main_dt_raw = (row[idx_main] or "").strip()
        if not main_dt_raw:
            continue

        # 跳過已取消
        if idx_status is not None and idx_status < len(row):
            st = (row[idx_status] or "").strip()
            if st == CANCELLED_TEXT or st.startswith("❌"):
                continue

        # 解析主班次時間
        date_str, time_str, dt = _parse_main_dt(main_dt_raw)
        if not date_str or not time_str or dt is None:
            continue

        if dt < min_dt:
            continue

        key = main_dt_raw  # 原始主班次時間字串當 trip_id

        if key not in trips:
            trips[key] = DriverTrip(
                trip_id=key,
                date=date_str,
                time=time_str,
                total_pax=0,
            )

        # 累計人數
        pax = 0
        if idx_pax is not None and 0 <= idx_pax < len(row):
            try:
                pax = int((row[idx_pax] or "0").strip() or "0")
            except Exception:
                pax = 0
        trips[key].total_pax += pax

    # 依主班次時間排序
    def sort_key(t: DriverTrip):
        try:
            dt = datetime.strptime(f"{t.date} {t.time}", "%Y-%m-%d %H:%M")
        except Exception:
            dt = datetime.max
        return dt

    return sorted(trips.values(), key=sort_key)


# ========= 2. 單一班次 → 依站點/上下車的乘客列表 =========

@app.get("/api/driver/trip_passengers", response_model=List[DriverPassenger])
def driver_get_trip_passengers(
    trip_id: str = Query(..., description="主班次時間原字串，例如 2025/12/08 17:00"),
):
    """
    司機用：取得指定「主班次時間」的乘客清單。
    每位乘客會拆成「上車」與「下車」兩筆（供班次畫面依站點分組用）。
    """
    ws_main = open_ws(SHEET_NAME_MAIN)
    hmap = header_map_main(ws_main)
    values = _read_all_rows(ws_main)

    col_main = hmap.get("主班次時間")
    if not values or not col_main:
        return []
    idx_main = col_main - 1

    idx_booking = hmap.get("預約編號", 0) - 1
    idx_name = hmap.get("姓名", 0) - 1
    idx_phone = hmap.get("手機", 0) - 1
    idx_room = hmap.get("房號", 0) - 1
    col_pax = hmap.get("確認人數") or hmap.get("預約人數")
    idx_pax = col_pax - 1 if col_pax else None
    idx_pick = hmap.get("上車地點", 0) - 1
    idx_drop = hmap.get("下車地點", 0) - 1
    idx_ride_status = hmap.get("乘車狀態", 0) - 1
    idx_qr = hmap.get("QRCode編碼", 0) - 1
    idx_dir = hmap.get("往返", 0) - 1
    idx_pick_idx = hmap.get("上車索引", 0) - 1
    idx_drop_idx = hmap.get("下車索引", 0) - 1

    result: List[DriverPassenger] = []

    for row in values[HEADER_ROW_MAIN:]:
        if not any(row):
            continue
        if idx_main >= len(row):
            continue

        main_dt_raw = (row[idx_main] or "").strip()
        if main_dt_raw != trip_id:
            continue

        booking_id = (row[idx_booking] if 0 <= idx_booking < len(row) else "").strip()
        name = (row[idx_name] if 0 <= idx_name < len(row) else "").strip()
        phone = (row[idx_phone] if 0 <= idx_phone < len(row) else "").strip()
        room = (row[idx_room] if 0 <= idx_room < len(row) else "").strip()
        ride_status = (row[idx_ride_status] if 0 <= idx_ride_status < len(row) else "").strip()
        qrcode = (row[idx_qr] if 0 <= idx_qr < len(row) else "").strip()
        direction = (row[idx_dir] if 0 <= idx_dir < len(row) else "").strip()

        if idx_pax is not None and 0 <= idx_pax < len(row):
            try:
                pax = int((row[idx_pax] or "1").strip() or "1")
            except Exception:
                pax = 1
        else:
            pax = 1

        pick = (row[idx_pick] if 0 <= idx_pick < len(row) else "").strip()
        drop = (row[idx_drop] if 0 <= idx_drop < len(row) else "").strip()

        # 站點排序：優先用 上車索引 / 下車索引
        pick_order = 99
        drop_order = 99
        if 0 <= idx_pick_idx < len(row):
            try:
                pick_order = int((row[idx_pick_idx] or "99").strip() or "99")
            except Exception:
                pick_order = 99
        if 0 <= idx_drop_idx < len(row):
            try:
                drop_order = int((row[idx_drop_idx] or "99").strip() or "99")
            except Exception:
                drop_order = 99

        # 上車
        if pick:
            result.append(
                DriverPassenger(
                    trip_id=trip_id,
                    main_departure=main_dt_raw,
                    station=pick,
                    updown="上車",
                    booking_id=booking_id,
                    name=name,
                    phone=phone,
                    room=room,
                    pax=pax,
                    status=ride_status,
                    qrcode=qrcode,
                    direction=direction,
                    station_order=pick_order,
                )
            )
        # 下車
        if drop:
            result.append(
                DriverPassenger(
                    trip_id=trip_id,
                    main_departure=main_dt_raw,
                    station=drop,
                    updown="下車",
                    booking_id=booking_id,
                    name=name,
                    phone=phone,
                    room=room,
                    pax=pax,
                    status=ride_status,
                    qrcode=qrcode,
                    direction=direction,
                    station_order=drop_order,
                )
            )

    # 排序：先按站點順序，再上/下車，再預約編號
    def sort_key(p: DriverPassenger):
        return (p.station_order, 0 if p.updown == "上車" else 1, p.booking_id)

    return sorted(result, key=sort_key)


# ========= 3. 全部乘客清單（右邊「乘客清單」大分頁） =========

@app.get("/api/driver/passenger_list", response_model=List[PassengerListRow])
def driver_passenger_list():
    """
    司機/主管用：全部未來乘客清單。
    結構對應你原本的 ARRAYFORMULA（出車總覽），每位乘客一列，
    5 個站別欄位：飯店(去)、捷運站、火車站、LaLaport、飯店(回)。
    """
    ws_main = open_ws(SHEET_NAME_MAIN)
    hmap = header_map_main(ws_main)
    values = _read_all_rows(ws_main)

    col_main = hmap.get("主班次時間")
    if not values or not col_main:
        return []

    idx_main = col_main - 1

    idx_car = hmap.get("車次", 0) - 1
    idx_booking = hmap.get("預約編號", 0) - 1
    idx_ride = hmap.get("乘車狀態", 0) - 1
    idx_dir = hmap.get("往返", 0) - 1
    idx_up = hmap.get("上車地點", 0) - 1
    idx_down = hmap.get("下車地點", 0) - 1
    idx_name = hmap.get("姓名", 0) - 1
    idx_phone = hmap.get("手機", 0) - 1
    idx_room = hmap.get("房號", 0) - 1
    col_pax = hmap.get("確認人數") or hmap.get("預約人數")
    idx_pax = col_pax - 1 if col_pax else None
    idx_status = hmap.get("預約狀態", 0) - 1

    now_dt = _tz_now_dt()
    # 這裡依公式：主班次時間 >= NOW()
    min_dt = now_dt - timedelta(minutes=1)

    rows: List[Tuple[Tuple, PassengerListRow]] = []

    for row in values[HEADER_ROW_MAIN:]:
        if not any(row):
            continue
        if idx_main >= len(row):
            continue

        main_raw = (row[idx_main] or "").strip()
        if not main_raw:
            continue

        # 解析主班次時間，並做時間過濾
        main_date, main_time, main_dt = _parse_main_dt(main_raw)
        if not main_date or not main_time or main_dt is None:
            continue
        if main_dt < min_dt:
            continue

        # 過濾已取消
        status_val = (row[idx_status] if 0 <= idx_status < len(row) else "").strip()
        if status_val == CANCELLED_TEXT or status_val.startswith("❌"):
            continue

        car = (row[idx_car] if 0 <= idx_car < len(row) else "").strip()
        booking_id = (row[idx_booking] if 0 <= idx_booking < len(row) else "").strip()
        ride_status = (row[idx_ride] if 0 <= idx_ride < len(row) else "").strip()
        direction = (row[idx_dir] if 0 <= idx_dir < len(row) else "").strip()
        up = (row[idx_up] if 0 <= idx_up < len(row) else "").strip()
        down = (row[idx_down] if 0 <= idx_down < len(row) else "").strip()
        name = (row[idx_name] if 0 <= idx_name < len(row) else "").strip()
        phone = (row[idx_phone] if 0 <= idx_phone < len(row) else "").strip()
        room = (row[idx_room] if 0 <= idx_room < len(row) else "").strip()

        if idx_pax is not None and 0 <= idx_pax < len(row):
            try:
                pax = int((row[idx_pax] or "1").strip() or "1")
            except Exception:
                pax = 1
        else:
            pax = 1

        up_n = up.strip()
        down_n = down.strip()

        # ===== stationSort（站點順序） =====
        if direction == "去程":
            if up_n == HOTEL:
                station_sort = 1
            elif up_n == MRT:
                station_sort = 2
            elif up_n == TRAIN:
                station_sort = 3
            elif up_n == MALL:
                station_sort = 4
            else:
                station_sort = 99
        elif direction == "回程":
            if up_n == MRT:
                station_sort = 1
            elif up_n == TRAIN:
                station_sort = 2
            elif up_n == MALL:
                station_sort = 3
            elif down_n == HOTEL:
                station_sort = 4
            else:
                station_sort = 99
        else:
            station_sort = 99

        # ===== dropoff_order（下車順序） =====
        if direction == "去程":
            if down_n == MRT:
                dropoff_order = 1
            elif down_n == TRAIN:
                dropoff_order = 2
            elif down_n == MALL:
                dropoff_order = 3
            else:
                dropoff_order = 4
        elif direction == "回程":
            if up_n == MALL:
                dropoff_order = 1
            elif up_n == TRAIN:
                dropoff_order = 2
            elif up_n == MRT:
                dropoff_order = 3
            else:
                dropoff_order = 99
        else:
            dropoff_order = 99

        # ===== 各站欄位：上/下/空 =====
        hotel_go = "上" if (direction == "去程" and up_n == HOTEL) else ""
        hotel_back = "下" if (direction == "回程" and down_n == HOTEL) else ""

        mrt_col = ""
        if up_n == MRT or down_n == MRT:
            mrt_col = "上" if up_n == MRT else "下"

        train_col = ""
        if up_n == TRAIN or down_n == TRAIN:
            train_col = "上" if up_n == TRAIN else "下"

        mall_col = ""
        if up_n == MALL or down_n == MALL:
            mall_col = "上" if up_n == MALL else "下"

        row_model = PassengerListRow(
            main_departure=main_raw,
            main_date=main_date,
            main_time=main_time,
            car=car,
            booking_id=booking_id,
            ride_status=ride_status,
            direction=direction,
            name=name,
            phone=phone,
            room=room,
            pax=pax,
            hotel_go=hotel_go,
            mrt=mrt_col,
            train=train_col,
            mall=mall_col,
            hotel_back=hotel_back,
            station_order=station_sort,
            dropoff_order=dropoff_order,
        )

        sort_key = (main_dt, direction, station_sort, dropoff_order, booking_id)
        rows.append((sort_key, row_model))

    rows.sort(key=lambda x: x[0])
    return [r for _, r in rows]


# ========= 4. 掃描 QRCode → 更新乘車狀態 =========

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

    rowno = _find_booking_row(values, hmap, booking_id)
    if rowno is None:
        return DriverCheckinResponse(
            status="not_found",
            message=f"找不到預約編號 {booking_id}",
        )

    from gspread.utils import rowcol_to_a1

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
                    "range": rowcol_to_a1(rowno, hmap[col_name]),
                    "values": [[value]],
                }
            )
    if batch_updates:
        ws_main.batch_update(batch_updates, value_input_option="USER_ENTERED")

    # 回傳給前端顯示
    def getv(col: str) -> str:
        return _get_cell_from_row(values[rowno - 1], hmap, col)

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
