from __future__ import annotations

import os
import time
from datetime import datetime, timedelta
from threading import Lock
from typing import Any, Dict, List, Optional, Tuple

import google.auth
import gspread
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import firebase_admin
from firebase_admin import credentials, db

# ========= Google Sheets 設定 =========

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

SPREADSHEET_ID = "1xp54tKOczklmT8uacW-HMxwV8r0VOR2ui33jYcE2pUQ"
SHEET_NAME_MAIN = "預約審核(櫃台)"
HEADER_ROW_MAIN = 2  # 第 2 列為表頭，資料從第 3 列起
SHEET_NAME_SYSTEM = "系統"

# 預約狀態文字（與 booking-manager 保持一致）
BOOKED_TEXT = "✔️ 已預約 Booked"
CANCELLED_TEXT = "❌ 已取消 Cancelled"

# ========= 快取設定 =========
# 目標：在 5 秒 TTL 內，所有讀取 API 都共用同一份 Sheet 資料，避免重複打 Google Sheets

CACHE_TTL_SECONDS = 5

# SHEET_CACHE 結構：
# {
#   "values": List[List[str]] 或 None,
#   "header_map": Dict[str, int] 或 None,
#   "fetched_at": datetime 或 None
# }
SHEET_CACHE: Dict[str, Any] = {
    "values": None,
    "header_map": None,
    "fetched_at": None,
}
CACHE_LOCK = Lock()

# ========= 司機即時位置 (In-Memory) =========
# 注意：若部署在 Serverless (Cloud Run) 且有多個實例，這裡的變數不會共享。
# 但考量只有一位司機，且通常會在同一實例處理，或可接受短暫不一致。
# 若需嚴格一致性，需寫入 Google Sheets 或 Redis。
DRIVER_LOCATION_CACHE: Dict[str, Any] = {
    "lat": 0.0,
    "lng": 0.0,
    "timestamp": 0.0,
    "updated_at": None
}
LOCATION_LOCK = Lock()


# ========= 共用時間工具 =========

def _tz_now() -> datetime:
    """台北時間 now（作為時間比較用）"""
    os.environ.setdefault("TZ", "Asia/Taipei")
    try:
        time.tzset()
    except Exception:
        # 某些環境不支援 tzset
        pass
    return datetime.now()


def _tz_now_str() -> str:
    """台北時間 now 的字串（寫回表格用）"""
    t = _tz_now()
    return t.strftime("%Y-%m-%d %H:%M:%S")


def _parse_main_dt(raw: str) -> Optional[datetime]:
    """解析主班次時間：可能是 '2025/12/08 18:30' 或 '2025-12-08 18:30' 等。"""
    if not raw:
        return None
    raw = raw.strip()
    for fmt in ("%Y/%m/%d %H:%M", "%Y-%m-%d %H:%M",
                "%Y/%m/%d %H:%M:%S", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(raw, fmt)
        except ValueError:
            continue
    # 有些可能只存日期
    for fmt in ("%Y/%m/%d", "%Y-%m-%d"):
        try:
            return datetime.strptime(raw, fmt)
        except ValueError:
            continue
    return None


def _safe_int(v: Any, default: int = 0) -> int:
    """安全轉 int，用在確認人數／人數欄位。"""
    try:
        s = str(v).strip()
        if not s:
            return default
        # 有些會是 1.0 之類
        return int(float(s))
    except Exception:
        return default


# ========= Google Sheets 基本操作 =========

def open_ws(name: str) -> gspread.Worksheet:
    """取得指定名稱的 Worksheet 物件。"""
    credentials, _ = google.auth.default(scopes=SCOPES)
    gc = gspread.authorize(credentials)
    sh = gc.open_by_key(SPREADSHEET_ID)
    return sh.worksheet(name)


def _sheet_headers(
    ws: gspread.Worksheet,
    header_row: int,
    values: Optional[List[List[str]]] = None,
) -> List[str]:
    """
    取得表頭列文字：
    - 若有提供 values，直接從 values 取第 header_row 列
    - 否則呼叫 ws.row_values(header_row) 讀取
    """
    if values is not None and len(values) >= header_row:
        headers = values[header_row - 1]
    else:
        headers = ws.row_values(header_row)
    return [(h or "").strip() for h in headers]


def header_map_main(
    ws: gspread.Worksheet,
    values: Optional[List[List[str]]] = None,
) -> Dict[str, int]:
    """
    依表頭名稱建立 map：欄名 -> 欄 index (1-based)。
    例如：{"主班次時間": 19, "預約編號": 3, ...}
    """
    row = _sheet_headers(ws, HEADER_ROW_MAIN, values)
    m: Dict[str, int] = {}
    for idx, name in enumerate(row, start=1):
        if name and name not in m:
            m[name] = idx
    return m


def _read_all_rows(ws: gspread.Worksheet) -> List[List[str]]:
    """整張表一次抓回 List[List[str]]。"""
    return ws.get_all_values()


def _find_qrcode_row(
    values: List[List[str]],
    hmap: Dict[str, int],
    qrcode_value: str,
) -> Optional[int]:
    """
    在『QRCode編碼』欄位裡，用「完整 qrcode 字串」找列。
    回傳工作表列號（1-based），找不到回傳 None。
    """
    col = hmap.get("QRCode編碼")
    if not col:
        return None
    ci = col - 1

    # values[0] 是第 1 列，values[HEADER_ROW_MAIN] 才是第 3 列資料
    for i, row in enumerate(values[HEADER_ROW_MAIN:], start=HEADER_ROW_MAIN + 1):
        if ci < len(row) and (row[ci] or "").strip() == qrcode_value:
            return i
    return None


def _col_index(hmap: Dict[str, int], name: str) -> int:
    """將欄名轉成 0-based index，若不存在回傳 -1。"""
    col = hmap.get(name)
    return col - 1 if col else -1


def _get_cell(row: List[str], idx: int) -> str:
    """安全讀取 row[idx] 並 strip，超出範圍或 idx<0 則回空字串。"""
    if idx < 0 or idx >= len(row):
        return ""
    return (row[idx] or "").strip()


# ========= Sheet 讀取快取核心 =========

def _get_sheet_data_main() -> Tuple[List[List[str]], Dict[str, int]]:
    """
    取得《預約審核(櫃台)》的整張表資料與 header_map。
    - 在 CACHE_TTL_SECONDS 內，如果 cache 有值，直接回傳 cache。
    - 超過 TTL 或 cache 無效時，重新讀取 Google Sheets 並更新 cache。
    """
    now = _tz_now()
    global SHEET_CACHE

    with CACHE_LOCK:
        cached_values = SHEET_CACHE.get("values")
        fetched_at: Optional[datetime] = SHEET_CACHE.get("fetched_at")

        if (
            cached_values is not None
            and fetched_at is not None
            and (now - fetched_at).total_seconds() < CACHE_TTL_SECONDS
        ):
            # 使用快取
            return cached_values, SHEET_CACHE["header_map"]

        # 重新讀取 Sheet
        ws = open_ws(SHEET_NAME_MAIN)
        values = _read_all_rows(ws)
        hmap = header_map_main(ws, values)

        SHEET_CACHE = {
            "values": values,
            "header_map": hmap,
            "fetched_at": now,
        }
        return values, hmap


def _invalidate_sheet_cache() -> None:
    """
    核銷（寫入）後呼叫，讓下一次讀取時一定會重新抓最新資料。
    """
    global SHEET_CACHE
    with CACHE_LOCK:
        SHEET_CACHE = {
            "values": None,
            "header_map": None,
            "fetched_at": None,
        }


# ========= Pydantic Models =========

class DriverTrip(BaseModel):
    trip_id: str   # 主班次時間原始字串（當 key）
    date: str      # YYYY-MM-DD
    time: str      # HH:MM
    total_pax: int


class DriverPassenger(BaseModel):
    trip_id: str
    station: str          # 站點名稱（1️⃣ 福泰大飯店..）
    updown: str           # "上車" / "下車"
    booking_id: str
    name: str
    phone: str
    room: str
    pax: int
    status: str           # "已上車" or ""
    direction: Optional[str] = None  # 去程 / 回程
    qrcode: str


class DriverAllPassenger(BaseModel):
    booking_id: str
    main_datetime: str    # 主班次時間原始字串
    depart_time: str      # HH:mm
    name: str
    phone: str
    room: str
    pax: int
    ride_status: str
    direction: str
    hotel_go: str
    mrt: str
    train: str
    mall: str
    hotel_back: str


class DriverCheckinRequest(BaseModel):
    qrcode: str  # FT:{booking_id}:{hash}


class DriverCheckinResponse(BaseModel):
    status: str
    message: str
    booking_id: Optional[str] = None
    name: Optional[str] = None
    pax: Optional[int] = None
    station: Optional[str] = None
    main_datetime: Optional[str] = None


class DriverLocation(BaseModel):
    lat: float
    lng: float
    timestamp: float

class BookingIdRequest(BaseModel):
    booking_id: str

class TripStatusRequest(BaseModel):
    main_datetime: str  # 格式: YYYY/MM/DD HH:MM
    status: str         # 已發車 / 已結束


class DriverAllData(BaseModel):
    """整合所有資料的回傳格式：一次給前端 trips / trip_passengers / passenger_list。"""
    trips: List[DriverTrip]
    trip_passengers: List[DriverPassenger]
    passenger_list: List[DriverAllPassenger]


# ========= 資料運算邏輯（純函數，不打 API） =========

def build_driver_trips(
    values: List[List[str]],
    hmap: Dict[str, int],
) -> List[DriverTrip]:
    """
    班次列表（主班次時間）：
    - 來源：整張《預約審核(櫃台)》
    - 條件：
        - 主班次時間存在
        - 主班次時間 >= NOW()-1 小時
        - 排除已取消（含 "❌" 或 CANCELLED_TEXT）
    - 結果：同一主班次時間彙總確認人數 total_pax
    """
    idx_main_dt = _col_index(hmap, "主班次時間")
    if idx_main_dt < 0:
        return []

    pax_col = hmap.get("確認人數", hmap.get("預約人數", 0))
    idx_pax = pax_col - 1 if pax_col else -1
    status_col = hmap.get("預約狀態")
    idx_status = status_col - 1 if status_col else -1

    now = _tz_now()
    cutoff = now - timedelta(hours=1)  # NOW() - 1/24

    trips_by_dt: Dict[str, DriverTrip] = {}

    for row in values[HEADER_ROW_MAIN:]:
        if not any(row):
            continue
        if idx_main_dt >= len(row):
            continue

        main_raw = _get_cell(row, idx_main_dt)
        if not main_raw:
            continue

        # 排除已取消（包含 ❌ 的都跳過）
        if idx_status >= 0 and idx_status < len(row):
            st = _get_cell(row, idx_status)
            if "❌" in st or st == CANCELLED_TEXT:
                continue

        dt = _parse_main_dt(main_raw)
        if not dt or dt < cutoff:
            continue

        date_str = dt.strftime("%Y-%m-%d")
        time_str = dt.strftime("%H:%M")

        if main_raw not in trips_by_dt:
            trips_by_dt[main_raw] = DriverTrip(
                trip_id=main_raw,
                date=date_str,
                time=time_str,
                total_pax=0,
            )

        if idx_pax >= 0 and idx_pax < len(row):
            trips_by_dt[main_raw].total_pax += _safe_int(row[idx_pax], 0)

    return sorted(trips_by_dt.values(), key=lambda t: (t.date, t.time))


def build_driver_trip_passengers(
    values: List[List[str]],
    hmap: Dict[str, int],
    trip_id: Optional[str] = None,
) -> List[DriverPassenger]:
    """
    指定班次乘客列表（依站點），或全部班次乘客：
    - 若 trip_id 為 None → 產生所有班次的乘客資料（前端可自行依 trip_id 篩選）
    - 若 trip_id 有值 → 僅產生該主班次時間的乘客
    - 每位乘客拆成「上車」與「下車」兩筆。
    """
    idx_main_dt = _col_index(hmap, "主班次時間")
    if idx_main_dt < 0:
        return []

    idx_booking = _col_index(hmap, "預約編號")
    idx_name = _col_index(hmap, "姓名")
    idx_phone = _col_index(hmap, "手機")
    idx_room = _col_index(hmap, "房號")
    pax_col = hmap.get("確認人數", hmap.get("預約人數", 0))
    idx_pax = pax_col - 1 if pax_col else -1
    idx_pick = _col_index(hmap, "上車地點")
    idx_drop = _col_index(hmap, "下車地點")
    idx_status = _col_index(hmap, "乘車狀態")
    idx_dir = _col_index(hmap, "往返")
    idx_qr = _col_index(hmap, "QRCode編碼")

    result: List[DriverPassenger] = []

    for row in values[HEADER_ROW_MAIN:]:
        if not any(row):
            continue
        if idx_main_dt >= len(row):
            continue

        main_raw = _get_cell(row, idx_main_dt)
        if not main_raw:
            continue

        if trip_id is not None and main_raw != trip_id:
            continue

        booking_id = _get_cell(row, idx_booking)
        name = _get_cell(row, idx_name)
        phone = _get_cell(row, idx_phone)
        room = _get_cell(row, idx_room)or "(餐客)"
        ride_status = _get_cell(row, idx_status)
        qrcode = _get_cell(row, idx_qr)
        direction = _get_cell(row, idx_dir)

        pax = 1
        if idx_pax >= 0 and idx_pax < len(row):
            pax = _safe_int(row[idx_pax], 1)

        pick = _get_cell(row, idx_pick)
        drop = _get_cell(row, idx_drop)

        # 上車
        if pick:
            result.append(
                DriverPassenger(
                    trip_id=main_raw,
                    station=pick,
                    updown="上車",
                    booking_id=booking_id,
                    name=name,
                    phone=phone,
                    room=room,
                    pax=pax,
                    status=ride_status,
                    direction=direction,
                    qrcode=qrcode,
                )
            )

        # 下車
        if drop:
            result.append(
                DriverPassenger(
                    trip_id=main_raw,
                    station=drop,
                    updown="下車",
                    booking_id=booking_id,
                    name=name,
                    phone=phone,
                    room=room,
                    pax=pax,
                    status=ride_status,
                    direction=direction,
                    qrcode=qrcode,
                )
            )

    def sort_key(p: DriverPassenger):
        # 站點字串前面有 1️⃣ 2️⃣...，字面排序就會是正確順序
        return (p.station, 0 if p.updown == "上車" else 1, p.booking_id)

    return sorted(result, key=sort_key)


def build_driver_all_passengers(
    values: List[List[str]],
    hmap: Dict[str, int],
) -> List[DriverAllPassenger]:
    """
    乘客清單（全部班次、照出車總覽公式）：
    完整模擬你在 Sheet 中那條「出車總覽」 ARRAYFORMULA + QUERY 的邏輯：
      - data 來源：預約審核(櫃台)
      - 用 主班次時間 >= NOW() 做篩選
      - 排除含「❌」的預約狀態
      - 依 主班次時間、往返、stationSort、dropoff_order 排序
      - 輸出欄位：車次、主班次時間、預約編號、乘車狀態、往返、
                  姓名、手機、房號、確認人數、
                  飯店(去)、捷運站、火車站、LaLaport、飯店(回)
    """
    def col_idx(name: str) -> int:
        return _col_index(hmap, name)

    idx_rid = col_idx("預約編號")
    idx_car_raw = col_idx("車次")
    idx_main_dt = col_idx("主班次時間")
    idx_dir = col_idx("往返")
    idx_up = col_idx("上車地點")
    idx_down = col_idx("下車地點")
    idx_name = col_idx("姓名")
    idx_phone = col_idx("手機")
    idx_room = col_idx("房號")
    idx_qty = col_idx("確認人數")
    idx_status = col_idx("預約狀態")
    idx_ride = col_idx("乘車狀態")

    if idx_main_dt < 0:
        return []

    # 站點文字（照你公式中使用的）
    hotel = "福泰大飯店 Forte Hotel"
    mrt = "南港展覽館捷運站 Nangang Exhibition Center - MRT Exit 3"
    train = "南港火車站 Nangang Train Station"
    mall = "LaLaport Shopping Park"

    now = _tz_now()

    base_rows: List[Dict[str, Any]] = []

    for row in values[HEADER_ROW_MAIN:]:
        if not any(row):
            continue
        if idx_main_dt >= len(row):
            continue

        main_raw = _get_cell(row, idx_main_dt)
        if not main_raw:
            continue

        dt = _parse_main_dt(main_raw)
        if not dt or dt < now:
            # 只有主班次時間 >= NOW 的才保留
            continue

        status_val = _get_cell(row, idx_status)
        if "❌" in status_val:
            # 排除已取消
            continue

        rid = _get_cell(row, idx_rid)
        car_raw = _get_cell(row, idx_car_raw)
        direction = _get_cell(row, idx_dir)
        up = _get_cell(row, idx_up)
        down = _get_cell(row, idx_down)
        name = _get_cell(row, idx_name)
        phone_raw = _get_cell(row, idx_phone)
        room_raw = _get_cell(row, idx_room)
        qty_raw = _get_cell(row, idx_qty)
        ride_status = _get_cell(row, idx_ride)

        phone_text = phone_raw if phone_raw else ""
        room_text = room_raw if room_raw else ""
        qty = _safe_int(qty_raw, 1)

        # sort_go
        if up == hotel:
            sort_go = 1
        elif up == mrt:
            sort_go = 2
        elif up == train:
            sort_go = 3
        elif up == mall:
            sort_go = 4
        else:
            sort_go = 99

        # sort_back
        if up == mrt:
            sort_back = 1
        elif up == train:
            sort_back = 2
        elif up == mall:
            sort_back = 3
        elif down == hotel:
            sort_back = 4
        else:
            sort_back = 99

        station_sort = sort_go if direction == "去程" else sort_back

        # hotel_go
        hotel_go = "上" if (direction == "去程" and up == hotel) else ""

        # mrt_col
        if up == mrt or down == mrt:
            mrt_col = "上" if up == mrt else "下"
        else:
            mrt_col = ""

        # train_col
        if up == train or down == train:
            train_col = "上" if up == train else "下"
        else:
            train_col = ""

        # mall_col
        if up == mall or down == mall:
            mall_col = "上" if up == mall else "下"
        else:
            mall_col = ""

        # hotel_back
        hotel_back = "下" if (direction == "回程" and down == hotel) else ""

        # dropoff_order
        if direction == "去程":
            if down == mrt:
                dropoff_order = 1
            elif down == train:
                dropoff_order = 2
            elif down == mall:
                dropoff_order = 3
            else:
                dropoff_order = 4
        elif direction == "回程":
            if up == mall:
                dropoff_order = 1
            elif up == train:
                dropoff_order = 2
            elif up == mrt:
                dropoff_order = 3
            else:
                dropoff_order = 4
        else:
            dropoff_order = 99

        base_rows.append(
            dict(
                car_raw=car_raw,
                main_dt_raw=main_raw,
                main_dt=dt,
                booking_id=rid,
                ride_status=ride_status,
                direction=direction,
                station_sort=station_sort,
                dropoff_order=dropoff_order,
                name=name,
                phone=phone_text,
                room=room_text,
                qty=qty,
                hotel_go=hotel_go,
                mrt=mrt_col,
                train=train_col,
                mall=mall_col,
                hotel_back=hotel_back,
            )
        )

    # 排序：主班次時間、往返、stationSort、dropoff_order
    def sort_key(row: Dict[str, Any]):
        dir_val = row["direction"] or ""
        # 去程先、回程後
        dir_rank = 0 if dir_val == "去程" else 1
        return (row["main_dt"], dir_rank, row["station_sort"], row["dropoff_order"])

    base_rows.sort(key=sort_key)

    result: List[DriverAllPassenger] = []
    for row in base_rows:
        dt = row["main_dt"]
        depart_time = dt.strftime("%H:%M") if dt else ""
        result.append(
            DriverAllPassenger(
                booking_id=row["booking_id"],
                main_datetime=row["main_dt_raw"],
                depart_time=depart_time,
                name=row["name"],
                phone=row["phone"],
                room=row["room"],
                pax=row["qty"],
                ride_status=row["ride_status"],
                direction=row["direction"],
                hotel_go=row["hotel_go"],
                mrt=row["mrt"],
                train=row["train"],
                mall=row["mall"],
                hotel_back=row["hotel_back"],
            )
        )

    return result


# ========= FastAPI App =========

app = FastAPI(title="Shuttle Driver API", version="3.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 現在允許所有來源，方便前端在各種網域使用
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health():
    return {"status": "ok", "time": _tz_now_str()}


# ========= 5. GPS 定位功能 =========

@app.post("/api/driver/location")
def update_driver_location(loc: DriverLocation):
    """
    接收司機端上傳的 GPS 座標
    """
    global DRIVER_LOCATION_CACHE
    with LOCATION_LOCK:
        DRIVER_LOCATION_CACHE["lat"] = loc.lat
        DRIVER_LOCATION_CACHE["lng"] = loc.lng
        DRIVER_LOCATION_CACHE["timestamp"] = loc.timestamp
        DRIVER_LOCATION_CACHE["updated_at"] = _tz_now_str()
    # 寫入 Firebase Realtime Database（若環境已設定）
    try:
        if not firebase_admin._apps:
            cred = credentials.ApplicationDefault()
            db_url = os.environ.get("FIREBASE_RTDB_URL")
            if not db_url:
                 project_id = os.environ.get("GOOGLE_CLOUD_PROJECT", "forte-booking-system")
                 db_url = f"https://{project_id}-default-rtdb.asia-southeast1.firebasedatabase.app/"
                 print(f"Warning: FIREBASE_RTDB_URL not set. Trying default: {db_url}")

            firebase_admin.initialize_app(cred, {"databaseURL": db_url})
        
        if firebase_admin._apps:
            ref = db.reference("/driver_location")
            ref.set({
                "lat": loc.lat,
                "lng": loc.lng,
                "timestamp": loc.timestamp,
                "updated_at": DRIVER_LOCATION_CACHE["updated_at"],
            })
            # print(f"Firebase write success: {loc.lat}, {loc.lng}")
    except Exception as e:
        print(f"Firebase write error: {e}")
    return {"status": "ok", "received": loc}


@app.get("/api/driver/location")
def get_driver_location():
    """
    取得司機最新位置 (供乘客端或地圖顯示使用)
    強制從 Firebase 讀取，不使用記憶體快取，以便除錯。
    """
    try:
        if not firebase_admin._apps:
             cred = credentials.ApplicationDefault()
             # 優先使用環境變數，若無則嘗試預設 URL
             db_url = os.environ.get("FIREBASE_RTDB_URL")
             if not db_url:
                 # 嘗試根據專案 ID 猜測預設 URL
                 # Cloud Run 的專案 ID 通常可從環境變數 GOOGLE_CLOUD_PROJECT 取得
                 project_id = os.environ.get("GOOGLE_CLOUD_PROJECT", "forte-booking-system")
                 # 嘗試常見的 Firebase RTDB URL 格式
                 db_url = f"https://{project_id}-default-rtdb.asia-southeast1.firebasedatabase.app/"
                 print(f"Warning: FIREBASE_RTDB_URL not set. Trying default: {db_url}")

             firebase_admin.initialize_app(cred, {"databaseURL": db_url})
        
        if firebase_admin._apps:
            ref = db.reference("/driver_location")
            data = ref.get()
            # print(f"Firebase read result: {data}")
            if data:
                return data
            else:
                return {"lat": 0, "lng": 0, "timestamp": 0, "status": "no_data_in_firebase"}
    except Exception as e:
        print(f"Firebase read error: {e}")
        # 回傳 500 但帶有詳細錯誤訊息，讓前端可以顯示
        return {
            "lat": 0, "lng": 0, "timestamp": 0, 
            "status": "error",
            "error_detail": str(e),
            "hint": "Check Cloud Run logs or FIREBASE_RTDB_URL env var."
        }

    # 只有在完全無法連線時才回傳空
    return {"lat": 0, "lng": 0, "timestamp": 0, "status": "firebase_not_initialized"}


# ========= 新整合端點：一次給 trips / trip_passengers / passenger_list =========

@app.get("/api/driver/data", response_model=DriverAllData)
def driver_get_all_data():
    """
    整合端點：
      - 讀取一次 Sheet（支援 5 秒快取）
      - 產生三種資料：
          1. trips           → 班次列表
          2. trip_passengers → 所有班次乘客（每人拆上/下車兩筆，含 trip_id 可供前端過濾）
          3. passenger_list  → 出車總覽（全部乘客）
    """
    values, hmap = _get_sheet_data_main()

    trips = build_driver_trips(values, hmap)
    trip_passengers = build_driver_trip_passengers(values, hmap, trip_id=None)
    passenger_list = build_driver_all_passengers(values, hmap)

    return DriverAllData(
        trips=trips,
        trip_passengers=trip_passengers,
        passenger_list=passenger_list,
    )


# ========= 兼容舊前端的三個端點（改用快取與共用邏輯） =========

@app.get("/api/driver/trips", response_model=List[DriverTrip])
def driver_get_trips():
    """
    班次列表（舊端點，現在改為使用快取與共用邏輯）。
    前端如果要更高效，可以改用 /api/driver/data。
    """
    values, hmap = _get_sheet_data_main()
    return build_driver_trips(values, hmap)


@app.get("/api/driver/trip_passengers", response_model=List[DriverPassenger])
def driver_get_trip_passengers(
    trip_id: str = Query(..., description="主班次時間原始字串，例如 2025/12/08 18:30"),
):
    """
    指定班次乘客列表（舊端點，現在改為使用快取與共用邏輯）。
    """
    values, hmap = _get_sheet_data_main()
    return build_driver_trip_passengers(values, hmap, trip_id=trip_id)


@app.get("/api/driver/passenger_list", response_model=List[DriverAllPassenger])
def driver_get_passenger_list():
    """
    乘客清單（出車總覽）（舊端點，現在改為使用快取與共用邏輯）。
    """
    values, hmap = _get_sheet_data_main()
    return build_driver_all_passengers(values, hmap)


# ========= 4. 掃描 QRCode → 更新乘車狀態（用 QRCode編碼，比對 ±30 分鐘，避免重複核銷） =========

@app.post("/api/driver/checkin", response_model=DriverCheckinResponse)
def api_driver_checkin(req: DriverCheckinRequest):
    """
    司機用：掃描 QRCode 後，將該訂單標記為「已上車」。

    QR 格式（例）：FT:20146958:2043d6

    規則：
    1. **只用『QRCode編碼』欄位** 比對整條 qrcode 字串，找出對應列
    2. 若「乘車狀態」已含「已上車」→ status = "already_checked_in"
       message = "此乘客已上車，不重複核銷"
    3. 取該列「主班次時間」，只有在『主班次時間 ± 30 分鐘』內才允許核銷
       - now > 主班次時間 + 30 分鐘 → status = "expired"（逾期）
       - now < 主班次時間 - 30 分鐘 → status = "not_started"（尚未發車）
       - 其餘 → 更新「乘車狀態」為「已上車」並寫入「最後操作時間」
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

    # 從 QRCode 中抓出 booking_id（純顯示用，不拿來找列）
    booking_id = parts[1].strip() if len(parts) >= 2 else ""

    # 這裡不使用快取，改為每次讀取最新資料，避免核銷判斷用到過舊資料
    ws = open_ws(SHEET_NAME_MAIN)
    values = _read_all_rows(ws)
    hmap = header_map_main(ws, values)

    # 一定要有 QRCode編碼 欄位
    if "QRCode編碼" not in hmap:
        raise HTTPException(500, "主表缺少『QRCode編碼』欄位")

    # 用「QRCode編碼」來找列（完整比對整條字串）
    rowno: Optional[int] = _find_qrcode_row(values, hmap, code)

    if rowno is None:
        return DriverCheckinResponse(
            status="not_found",
            message="找不到對應的預約（QRCode編碼）",
        )

    # 直接從 values 取值
    row_idx = rowno - 1  # values 的 index
    row = values[row_idx] if 0 <= row_idx < len(values) else []

    def getv(col_name: str) -> str:
        ci = hmap.get(col_name, 0) - 1
        if ci < 0 or ci >= len(row):
            return ""
        return row[ci] or ""

    # 以表格內容為準更新 booking_id（避免將來格式調整）
    sheet_booking_id = getv("預約編號").strip()
    if sheet_booking_id:
        booking_id = sheet_booking_id

    # 先檢查是否已經「已上車」→ 不重複核銷
    ride_status_current = getv("乘車狀態").strip()
    if ride_status_current and ("已上車" in ride_status_current):
        pax_str = getv("確認人數") or getv("預約人數") or "1"
        pax = _safe_int(pax_str, 1)
        return DriverCheckinResponse(
            status="already_checked_in",
            message="此乘客已上車，不重複核銷",
            booking_id=booking_id or None,
            name=getv("姓名") or None,
            pax=pax,
            station=getv("上車地點") or None,
            main_datetime=main_dt.strftime("%Y/%m/%d %H:%M"),
        )

    # 取得主班次時間，並做 ±30 分鐘判斷
    main_raw = getv("主班次時間").strip()
    if not main_raw:
        return DriverCheckinResponse(
            status="error",
            message="此預約缺少『主班次時間』，無法核銷上車",
            booking_id=booking_id or None,
        )

    main_dt = _parse_main_dt(main_raw)
    if not main_dt:
        return DriverCheckinResponse(
            status="error",
            message=f"主班次時間格式錯誤：{main_raw}",
            booking_id=booking_id or None,
        )

    now = _tz_now()
    diff_sec = (now - main_dt).total_seconds()
    
    limit_before = 30 * 60  # 30 分鐘前
    limit_after = 60 * 60   # 60 分鐘後

    # 太晚：逾期 (超過班次時間 60 分鐘)
    if diff_sec > limit_after:
        pax_str = getv("確認人數") or getv("預約人數") or "1"
        pax = _safe_int(pax_str, 1)
        return DriverCheckinResponse(
            status="expired",
            message="此班次已逾期，無法核銷上車",
            booking_id=booking_id or None,
            name=getv("姓名") or None,
            pax=pax,
            station=getv("上車地點") or None,
            main_datetime=main_dt.strftime("%Y/%m/%d %H:%M"),
        )

    # 太早：尚未發車 (早於班次時間 30 分鐘)
    if diff_sec < -limit_before:
        dt_str = main_dt.strftime("%Y/%m/%d %H:%M")
        pax_str = getv("確認人數") or getv("預約人數") or "1"
        pax = _safe_int(pax_str, 1)
        return DriverCheckinResponse(
            status="not_started",
            message=f"{dt_str} 班次，尚未發車",
            booking_id=booking_id or None,
            name=getv("姓名") or None,
            pax=pax,
            station=getv("上車地點") or None,
            main_datetime=dt_str,
        )

    # OK：在允許時間範圍內，允許核銷 → 更新乘車狀態 / 最後操作時間
    updates: Dict[str, str] = {}
    if "乘車狀態" in hmap:
        updates["乘車狀態"] = "已上車"
    if "最後操作時間" in hmap:
        updates["最後操作時間"] = _tz_now_str() + " 已上車(司機)"

    from gspread.utils import rowcol_to_a1

    if updates:
        data = []
        for col_name, val in updates.items():
            ci = hmap[col_name]
            data.append(
                {
                    "range": rowcol_to_a1(rowno, ci),
                    "values": [[val]],
                }
            )
        ws.batch_update(data, value_input_option="USER_ENTERED")

    # 核銷成功後，清除快取，下次讀資料會重新載入最新表內容
    _invalidate_sheet_cache()

    # 回傳給前端顯示
    pax_str = getv("確認人數") or getv("預約人數") or "1"
    pax = _safe_int(pax_str, 1)

    return DriverCheckinResponse(
        status="success",
        message="已完成上車紀錄",
        booking_id=booking_id or None,
        name=getv("姓名") or None,
        pax=pax,
        station=getv("上車地點") or None,
        main_datetime=main_dt.strftime("%Y/%m/%d %H:%M"),
    )


@app.post("/api/driver/no_show")
def api_driver_no_show(req: BookingIdRequest):
    values, hmap = _get_sheet_data_main()
    ws = open_ws(SHEET_NAME_MAIN)
    idx_booking = _col_index(hmap, "預約編號")
    if idx_booking < 0:
        raise HTTPException(status_code=400, detail="找不到『預約編號』欄位")
    target_rowno: Optional[int] = None
    for i, row in enumerate(values[HEADER_ROW_MAIN:], start=HEADER_ROW_MAIN + 1):
        if idx_booking < len(row) and (row[idx_booking] or "").strip() == req.booking_id:
            target_rowno = i
            break
    if not target_rowno:
        raise HTTPException(status_code=404, detail="找不到對應預約編號")
    from gspread.utils import rowcol_to_a1
    data = []
    if "乘車狀態" in hmap:
        data.append({"range": rowcol_to_a1(target_rowno, hmap["乘車狀態"]), "values": [["No-show"]]})
    if "最後操作時間" in hmap:
        data.append({"range": rowcol_to_a1(target_rowno, hmap["最後操作時間"]), "values": [[_tz_now_str() + " No-show(司機)"]]})
    if data:
        ws.batch_update(data, value_input_option="USER_ENTERED")
    _invalidate_sheet_cache()
    return {"status": "success"}


@app.post("/api/driver/manual_boarding")
def api_driver_manual_boarding(req: BookingIdRequest):
    values, hmap = _get_sheet_data_main()
    ws = open_ws(SHEET_NAME_MAIN)
    idx_booking = _col_index(hmap, "預約編號")
    if idx_booking < 0:
        raise HTTPException(status_code=400, detail="找不到『預約編號』欄位")
    target_rowno: Optional[int] = None
    for i, row in enumerate(values[HEADER_ROW_MAIN:], start=HEADER_ROW_MAIN + 1):
        if idx_booking < len(row) and (row[idx_booking] or "").strip() == req.booking_id:
            target_rowno = i
            break
    if not target_rowno:
        raise HTTPException(status_code=404, detail="找不到對應預約編號")
    from gspread.utils import rowcol_to_a1
    data = []
    if "乘車狀態" in hmap:
        data.append({"range": rowcol_to_a1(target_rowno, hmap["乘車狀態"]), "values": [["已上車"]]})
    if "最後操作時間" in hmap:
        data.append({"range": rowcol_to_a1(target_rowno, hmap["最後操作時間"]), "values": [[_tz_now_str() + " 人工驗票(司機)"]]})
    if data:
        ws.batch_update(data, value_input_option="USER_ENTERED")
    _invalidate_sheet_cache()
    return {"status": "success"}


@app.post("/api/driver/trip_status")
def api_driver_trip_status(req: TripStatusRequest):
    sheet_name = "車次管理(櫃台)"
    try:
        ws = open_ws(sheet_name)
    except Exception:
        ws = open_ws("車次管理(備品)")
    headers = ws.row_values(6)
    headers = [(h or "").strip() for h in headers]
    def hidx(name: str) -> int:
        try:
            return headers.index(name)
        except ValueError:
            return -1
    idx_date = hidx("日期")
    idx_time = hidx("時間")
    if idx_time < 0:
        idx_time = hidx("班次")
    idx_status = hidx("出車狀態")
    idx_last = hidx("最後更新")
    if min(idx_date, idx_time, idx_status, idx_last) < 0:
        raise HTTPException(status_code=400, detail="表頭缺少必要欄位")
    # 解析傳入主班次時間（YYYY/MM/DD HH:MM）
    raw = req.main_datetime.strip()
    parts = raw.split(" ")
    if len(parts) < 2:
        raise HTTPException(status_code=400, detail="主班次時間格式錯誤")
    target_date, target_time = parts[0], parts[1]
    def norm_dates(d: str) -> list:
        d = d.strip()
        if "-" in d:
            y,m,day = d.split("-")
        else:
            y,m,day = d.split("/")
        m2 = str(m).zfill(2)
        d2 = str(day).zfill(2)
        return [f"{y}/{m2}/{d2}", f"{y}-{m2}-{d2}"]
    def norm_time(t: str) -> list:
        t = t.strip()
        parts = t.split(":")
        if len(parts) == 1:
            return [t]
        h = parts[0]
        mm = parts[1] if len(parts) > 1 else "00"
        ss = parts[2] if len(parts) > 2 else None
        h2 = str(h).zfill(2)
        res = [f"{h2}:{mm}", f"{int(h)}:{mm}"]
        if ss is not None:
            res.append(f"{h2}:{mm}:{ss}")
        return res
    t_dates = norm_dates(target_date)
    t_times = norm_time(target_time)
    # 從第 7 列開始找
    values = ws.get_all_values()
    target_rowno: Optional[int] = None
    for i in range(6, len(values)):
        row = values[i]
        d = (row[idx_date] if idx_date < len(row) else "").strip()
        t_raw = (row[idx_time] if idx_time < len(row) else "").strip()
        # Normalize row time HH:MM
        try:
            rp = t_raw.split(":")
            t_norm = f"{str(rp[0]).zfill(2)}:{rp[1]}" if len(rp) >= 2 else t_raw
        except Exception:
            t_norm = t_raw
        if (d in t_dates) and (t_raw in t_times or t_norm in t_times):
            target_rowno = i + 1  # 1-based
            break
    if not target_rowno:
        raise HTTPException(status_code=404, detail="找不到對應主班次時間")
    from gspread.utils import rowcol_to_a1
    now_text = _tz_now().strftime("%Y/%m/%d %H:%M")
    data = [
        {"range": rowcol_to_a1(target_rowno, idx_status + 1), "values": [[req.status]]},
        {"range": rowcol_to_a1(target_rowno, idx_last + 1), "values": [[now_text]]},
    ]
    ws.batch_update(data, value_input_option="USER_ENTERED")
    return {"status": "success"}
class QrInfoRequest(BaseModel):
    qrcode: str
class QrInfoResponse(BaseModel):
    booking_id: Optional[str]
    name: Optional[str]
    main_datetime: Optional[str]
    ride_status: Optional[str]
    station_up: Optional[str]
    station_down: Optional[str]
@app.post("/api/driver/qrcode_info", response_model=QrInfoResponse)
def api_driver_qrinfo(req: QrInfoRequest):
    values, hmap = _get_sheet_data_main()
    ws = open_ws(SHEET_NAME_MAIN)
    rowno = _find_qrcode_row(values, hmap, req.qrcode)
    if not rowno:
        return QrInfoResponse(booking_id=None, name=None, main_datetime=None, ride_status=None, station_up=None, station_down=None)
    row = values[rowno-1]
    def getv(col: str) -> str:
        ci = hmap.get(col, 0)-1
        return (row[ci] if 0 <= ci < len(row) else "").strip()
    main_raw = getv("主班次時間")
    return QrInfoResponse(
        booking_id=getv("預約編號") or None,
        name=getv("姓名") or None,
        main_datetime=main_raw or None,
        ride_status=getv("乘車狀態") or None,
        station_up=getv("上車地點") or None,
        station_down=getv("下車地點") or None,
    )

# ========= Google Trip API（改用 Google 流程，不依賴 HyperTrack） =========

class GoogleTripStartRequest(BaseModel):
    main_datetime: str
    driver_role: Optional[str] = None

class GoogleTripStartResponse(BaseModel):
    trip_id: Optional[str] = None
    share_url: Optional[str] = None
    stops: Optional[List[Dict[str, float]]] = None

class GoogleTripCompleteRequest(BaseModel):
    trip_id: str
    driver_role: Optional[str] = None

@app.post("/api/driver/google/trip_start", response_model=GoogleTripStartResponse)
def api_driver_google_trip_start(req: GoogleTripStartRequest):
    dt = _parse_main_dt(req.main_datetime)
    if not dt:
        raise HTTPException(status_code=400, detail="主班次時間格式錯誤")
    trip_id = dt.strftime("%Y/%m/%d %H:%M")
    # 系統啟用旗標：系統!E19 為 TRUE 才啟用追蹤
    try:
        ws = open_ws(SHEET_NAME_SYSTEM)
        e19 = (ws.acell("E19").value or "").strip().lower()
        enabled = e19 in ("true", "t", "yes", "1")
    except Exception:
        enabled = True  # 若讀取失敗，預設啟用（可依需求改為 False）
    if not enabled:
        return GoogleTripStartResponse(trip_id=None, share_url=None, stops=None)
    # 產生乘客端地圖分享 URL（使用環境變數指定基底網址）
    base = os.environ.get("PASSENGER_MAP_URL_BASE", "")
    api_base = os.environ.get("DRIVER_API_BASE", "")
    query = []
    if base:
        if os.environ.get("VITE_GOOGLE_MAPS_API_KEY"):
            query.append("key=" + os.environ.get("VITE_GOOGLE_MAPS_API_KEY"))
        if api_base:
            query.append("api=" + api_base)
        share_url = base + ("?" + "&".join(query) if query else "")
    else:
        share_url = ""  # 未設定則留空
    # 將 URL 寫入 系統!D19
    try:
        if share_url:
            ws.update("D19", share_url)
    except Exception:
        pass
    # 範例 stops（可改為從 Sheet/行程計算）
    lat, lng = 25.068, 121.662
    return GoogleTripStartResponse(trip_id=trip_id, share_url=share_url or None, stops=[{"lat": lat, "lng": lng}])

@app.post("/api/driver/google/trip_complete")
def api_driver_google_trip_complete(req: GoogleTripCompleteRequest):
    if not req.trip_id:
        raise HTTPException(status_code=400, detail="缺少 trip_id")
    # 此端點目前僅作為狀態回報，不寫入 Sheets。
    return {"status": "success"}
