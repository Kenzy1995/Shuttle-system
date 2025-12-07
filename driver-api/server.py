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

# ✅ 和 booking-manager 使用同一份試算表
SPREADSHEET_ID = "1xp54tKOczklmT8uacW-HMxwV8r0VOR2ui33jYcE2pUQ"
SHEET_NAME_MAIN = "預約審核(櫃台)"
HEADER_ROW_MAIN = 2  # 第二列是表頭，資料從第三列起

BOOKED_TEXT = "✔️ 已預約 Booked"
CANCELLED_TEXT = "❌ 已取消 Cancelled"

# 五個站點（要和主表的文字一致）
HOTEL = "福泰大飯店 Forte Hotel"
MRT = "南港展覽館捷運站 Nangang Exhibition Center - MRT Exit 3"
TRAIN = "南港火車站 Nangang Train Station"
MALL = "LaLaport Shopping Park"

STATION_LABELS = {
    1: "1️⃣ 福泰大飯店 (去)",
    2: "2️⃣ 南港捷運站",
    3: "3️⃣ 南港火車站",
    4: "4️⃣ LaLaport 購物中心",
    5: "5️⃣ 福泰大飯店 (回)",
}


# ========= 共用小工具 =========

def _tz_now_dt() -> datetime:
    """台北時間 now（naive datetime，用來做 >= 比較）"""
    os.environ.setdefault("TZ", "Asia/Taipei")
    try:
        time.tzset()
    except Exception:
        pass
    lt = time.localtime()
    return datetime(lt.tm_year, lt.tm_mon, lt.tm_mday, lt.tm_hour, lt.tm_min, lt.tm_sec)


def _tz_now_str() -> str:
    return _tz_now_dt().strftime("%Y-%m-%d %H:%M:%S")


def _parse_main_datetime(s: str) -> Optional[datetime]:
    """解析主班次時間，支援 2025/12/08 18:30 或 2025-12-08 18:30。"""
    s = (s or "").strip()
    if not s:
        return None
    for fmt in ("%Y/%m/%d %H:%M", "%Y-%m-%d %H:%M"):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    # 若只有日期
    for fmt in ("%Y/%m/%d", "%Y-%m-%d"):
        try:
            d = datetime.strptime(s, fmt)
            return d
        except ValueError:
            continue
    return None


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
    表頭名稱 -> 欄位位置 (1-based)
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
    """用『預約編號』找到整張表中的 row number (1-based)。"""
    col = hmap.get("預約編號")
    if not col:
        return None
    col_idx = col - 1
    for i, row in enumerate(values[HEADER_ROW_MAIN:], start=HEADER_ROW_MAIN + 1):
        if col_idx < len(row) and (row[col_idx] or "").strip() == booking_id:
            return i
    return None


def _station_eq(a: str, b: str) -> bool:
    return (a or "").strip() == (b or "").strip()


# ========= Pydantic Models =========

class DriverTrip(BaseModel):
    """左下【預計出車】列表用"""
    trip_id: str        # = 主班次時間原始字串（例如 "2025/12/08 18:30"）
    date: str           # "2025/12/08"
    time: str           # "18:30"
    total_pax: int


class DriverPassenger(BaseModel):
    """
    某個班次 → 乘客列表（會依站點拆成上/下兩筆）
    用在：進入班次後的畫面，依站點分組。
    """
    trip_id: str
    station: str        # 例如 "4️⃣ LaLaport 購物中心"
    updown: str         # "上車" / "下車"
    booking_id: str
    name: str
    phone: str
    room: str
    pax: int
    status: str         # "已上車" 或 ""
    qrcode: str         # QRCode 編碼內容


class PassengerOverview(BaseModel):
    """
    右下【乘客清單】大分頁用：一位乘客一筆，五個站別是欄位。
    """
    trip_id: str        # 主班次時間原始字串 (ex: "2025/12/08 18:30")
    date: str           # "2025/12/08"
    time: str           # "18:30"
    booking_id: str
    ride_status: str    # 乘車狀態
    direction: str      # 往返：去程/回程
    name: str
    phone: str
    room: str
    pax: int
    hotel_go: str       # 飯店(去) 欄位：上/下/空白
    mrt: str            # 捷運站
    train: str          # 火車站
    mall: str           # LaLaport
    hotel_back: str     # 飯店(回)


class DriverCheckinRequest(BaseModel):
    qrcode: str        # FT:{booking_id}:{hash}


class DriverCheckinResponse(BaseModel):
    status: str        # "success" / "not_found" / "error"
    message: str
    booking_id: Optional[str] = None
    name: Optional[str] = None
    pax: Optional[int] = None
    station: Optional[str] = None


# ========= FastAPI App =========

app = FastAPI(title="Shuttle Driver API", version="2.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:8080",
        "http://127.0.0.1:8080",
        # 之後可加正式網域
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health():
    return {"status": "ok", "time": _tz_now_str()}


# ========= 1. 取得【預計出車】班次列表 =========

@app.get("/api/driver/trips", response_model=List[DriverTrip])
def driver_get_trips():
    """
    依『主班次時間』彙總未來班次：
    - 主班次時間 有值
    - 主班次時間 >= (現在 - 1 小時)
    - 預約狀態 不含 ❌
    """
    ws_main = open_ws(SHEET_NAME_MAIN)
    hmap = header_map_main(ws_main)
    values = _read_all_rows(ws_main)

    if not values or "主班次時間" not in hmap:
        return []

    idx_main = hmap["主班次時間"] - 1
    idx_pax_col = hmap.get("確認人數", hmap.get("預約人數", 0))
    idx_pax = idx_pax_col - 1 if idx_pax_col else None
    idx_status_col = hmap.get("預約狀態")
    idx_status = idx_status_col - 1 if idx_status_col else None

    now_dt = _tz_now_dt() - timedelta(hours=1)

    trips: Dict[str, DriverTrip] = {}

    for row in values[HEADER_ROW_MAIN:]:
        if not any(row):
            continue
        if idx_main >= len(row):
            continue

        main_raw = (row[idx_main] or "").strip()
        if not main_raw:
            continue

        dt = _parse_main_datetime(main_raw)
        if not dt:
            continue

        # 只留近期班次
        if dt < now_dt:
            continue

        # 預約狀態過濾（含 "❌" 就跳過）
        if idx_status is not None and idx_status < len(row):
            st = (row[idx_status] or "").strip()
            if "❌" in st:
                continue

        date_str = dt.strftime("%Y/%m/%d")
        time_str = dt.strftime("%H:%M")
        key = main_raw  # trip_id

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

    return sorted(trips.values(), key=lambda t: (t.date, t.time))


# ========= 2. 某班次 → 乘客列表（依站點拆上下車） =========

@app.get("/api/driver/trip_passengers", response_model=List[DriverPassenger])
def driver_get_trip_passengers(
    trip_id: str = Query(..., description="主班次時間，例如 2025/12/08 18:30")
):
    """
    司機用：指定『主班次時間』，取得該班次所有乘客的上下車明細。
    - 一位乘客會拆成「上車」與「下車」兩筆（如果有設定）
    - 站點排序依上/下車索引 (1~5)，對應 STATION_LABELS
    """
    ws_main = open_ws(SHEET_NAME_MAIN)
    hmap = header_map_main(ws_main)
    values = _read_all_rows(ws_main)

    if not values or "主班次時間" not in hmap:
        return []

    idx_main = hmap["主班次時間"] - 1

    idx_booking = hmap.get("預約編號", 0) - 1
    idx_name = hmap.get("姓名", 0) - 1
    idx_phone = hmap.get("手機", 0) - 1
    idx_room = hmap.get("房號", 0) - 1
    idx_pax_col = hmap.get("確認人數", hmap.get("預約人數", 0))
    idx_pax = idx_pax_col - 1 if idx_pax_col else None
    idx_status = hmap.get("乘車狀態", 0) - 1
    idx_qr = hmap.get("QRCode編碼", 0) - 1
    idx_pick_idx = hmap.get("上車索引", 0) - 1
    idx_drop_idx = hmap.get("下車索引", 0) - 1

    tmp: List[Tuple[int, int, DriverPassenger]] = []

    for row in values[HEADER_ROW_MAIN:]:
        if not any(row):
            continue
        if idx_main >= len(row):
            continue

        main_raw = (row[idx_main] or "").strip()
        if main_raw != trip_id:
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

        # 上車站
        if 0 <= idx_pick_idx < len(row):
            try:
                pick_idx = int((row[idx_pick_idx] or "").strip() or "0")
            except Exception:
                pick_idx = 0
            if pick_idx in STATION_LABELS:
                p = DriverPassenger(
                    trip_id=trip_id,
                    station=STATION_LABELS[pick_idx],
                    updown="上車",
                    booking_id=booking_id,
                    name=name,
                    phone=phone,
                    room=room,
                    pax=pax,
                    status=status,
                    qrcode=qrcode,
                )
                tmp.append((pick_idx, 0, p))

        # 下車站
        if 0 <= idx_drop_idx < len(row):
            try:
                drop_idx = int((row[idx_drop_idx] or "").strip() or "0")
            except Exception:
                drop_idx = 0
            if drop_idx in STATION_LABELS:
                p2 = DriverPassenger(
                    trip_id=trip_id,
                    station=STATION_LABELS[drop_idx],
                    updown="下車",
                    booking_id=booking_id,
                    name=name,
                    phone=phone,
                    room=room,
                    pax=pax,
                    status=status,
                    qrcode=qrcode,
                )
                tmp.append((drop_idx, 1, p2))

    tmp.sort(key=lambda x: (x[0], x[1], x[2].booking_id))
    return [t[2] for t in tmp]


# ========= 3. 全部乘客清單（右下大分頁） =========

@app.get("/api/driver/passenger_overview", response_model=List[PassengerOverview])
def driver_passenger_overview():
    """
    右下【乘客清單】：
    - 一位乘客一筆
    - 欄位：預約編號、姓名、房號、人數、飯店(去)、捷運站、火車站、LaLaport、飯店(回)
    - 依主班次時間、往返、站點排序、dropoff 排序
    """
    ws_main = open_ws(SHEET_NAME_MAIN)
    hmap = header_map_main(ws_main)
    values = _read_all_rows(ws_main)

    required = ["主班次時間", "預約編號", "往返", "姓名",
                "手機", "房號", "確認人數", "預約狀態",
                "上車地點", "下車地點", "乘車狀態"]
    for col in required:
        if col not in hmap and not (col == "確認人數" and "預約人數" in hmap):
            # 人數允許用 預約人數 代替
            raise HTTPException(500, f"主表缺少欄位：{col}")

    idx_main = hmap["主班次時間"] - 1
    idx_rid = hmap.get("預約編號") - 1
    idx_dir = hmap.get("往返") - 1
    idx_name = hmap.get("姓名") - 1
    idx_phone = hmap.get("手機") - 1
    idx_room = hmap.get("房號") - 1
    idx_pax_col = hmap.get("確認人數", hmap.get("預約人數"))
    idx_pax = idx_pax_col - 1
    idx_status_main = hmap.get("預約狀態") - 1
    idx_up = hmap.get("上車地點") - 1
    idx_down = hmap.get("下車地點") - 1
    idx_ride_status = hmap.get("乘車狀態") - 1

    now_dt = _tz_now_dt()

    tmp: List[Tuple[datetime, str, int, int, PassengerOverview]] = []

    for row in values[HEADER_ROW_MAIN:]:
        if not any(row):
            continue
        if idx_main >= len(row):
            continue

        main_raw = (row[idx_main] or "").strip()
        if not main_raw:
            continue

        main_dt = _parse_main_datetime(main_raw)
        if not main_dt:
            continue

        # 主班次時間 >= 現在
        if main_dt < now_dt:
            continue

        # 預約狀態過濾（含❌就略過）
        status_main = (row[idx_status_main] if 0 <= idx_status_main < len(row) else "").strip()
        if "❌" in status_main:
            continue

        booking_id = (row[idx_rid] if 0 <= idx_rid < len(row) else "").strip()
        direction = (row[idx_dir] if 0 <= idx_dir < len(row) else "").strip()
        name = (row[idx_name] if 0 <= idx_name < len(row) else "").strip()
        phone = (row[idx_phone] if 0 <= idx_phone < len(row) else "").strip()
        room = (row[idx_room] if 0 <= idx_room < len(row) else "").strip()
        ride_status = (row[idx_ride_status] if 0 <= idx_ride_status < len(row) else "").strip()

        try:
            pax = int((row[idx_pax] if 0 <= idx_pax < len(row) else "1").strip() or "1")
        except Exception:
            pax = 1

        up = (row[idx_up] if 0 <= idx_up < len(row) else "").strip()
        down = (row[idx_down] if 0 <= idx_down < len(row) else "").strip()

        # === 照你的公式把 stationSort / dropoff_order & 五個欄位算出來 ===
        up_hotel = _station_eq(up, HOTEL)
        up_mrt = _station_eq(up, MRT)
        up_train = _station_eq(up, TRAIN)
        up_mall = _station_eq(up, MALL)
        down_hotel = _station_eq(down, HOTEL)
        down_mrt = _station_eq(down, MRT)
        down_train = _station_eq(down, TRAIN)
        down_mall = _station_eq(down, MALL)

        # sort_go
        if up_hotel:
            sort_go = 1
        elif up_mrt:
            sort_go = 2
        elif up_train:
            sort_go = 3
        elif up_mall:
            sort_go = 4
        else:
            sort_go = 99

        # sort_back
        if up_mrt:
            sort_back = 1
        elif up_train:
            sort_back = 2
        elif up_mall:
            sort_back = 3
        elif down_hotel:
            sort_back = 4
        else:
            sort_back = 99

        if direction == "去程":
            station_sort = sort_go
        elif direction == "回程":
            station_sort = sort_back
        else:
            station_sort = 99

        # 五個站點欄位：上 / 下 / 空白
        hotel_go = "上" if (direction == "去程" and up_hotel) else ""
        mrt_col = ""
        if up_mrt or down_mrt:
            mrt_col = "上" if up_mrt else "下"
        train_col = ""
        if up_train or down_train:
            train_col = "上" if up_train else "下"
        mall_col = ""
        if up_mall or down_mall:
            mall_col = "上" if up_mall else "下"
        hotel_back = "下" if (direction == "回程" and down_hotel) else ""

        # dropoff_order
        if direction == "去程":
            if down_mrt:
                dropoff_order = 1
            elif down_train:
                dropoff_order = 2
            elif down_mall:
                dropoff_order = 3
            else:
                dropoff_order = 4
        elif direction == "回程":
            if up_mrt:
                dropoff_order = 3
            elif up_train:
                dropoff_order = 2
            elif up_mall:
                dropoff_order = 1
            else:
                dropoff_order = 4
        else:
            dropoff_order = 99

        date_str = main_dt.strftime("%Y/%m/%d")
        time_str = main_dt.strftime("%H:%M")

        po = PassengerOverview(
            trip_id=main_raw,
            date=date_str,
            time=time_str,
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
        )

        tmp.append((main_dt, direction, station_sort, dropoff_order, po))

    # 依主班次時間、往返、station_sort、dropoff_order 排序
    tmp.sort(key=lambda x: (x[0], x[1], x[2], x[3]))
    return [t[4] for t in tmp]


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

    def getv(col: str) -> str:
        if col not in hmap:
            return ""
        return ws_main.cell(rowno, hmap[col]).value or ""

    # 更新「乘車狀態」與「最後操作時間」
    from gspread.utils import rowcol_to_a1

    updates: List[Dict[str, Any]] = []
    if "乘車狀態" in hmap:
        updates.append(
            {
                "range": rowcol_to_a1(rowno, hmap["乘車狀態"]),
                "values": [["已上車"]],
            }
        )
    if "最後操作時間" in hmap:
        updates.append(
            {
                "range": rowcol_to_a1(rowno, hmap["最後操作時間"]),
                "values": [[_tz_now_str() + " 已上車(司機)"]],
            }
        )

    if updates:
        ws_main.batch_update(updates, value_input_option="USER_ENTERED")

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
