from __future__ import annotations
import os
import time
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

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
HEADER_ROW_MAIN = 2  # 第 2 列為表頭，資料從第 3 列起

# 預約狀態文字（與 booking-manager 保持一致）
BOOKED_TEXT = "✔️ 已預約 Booked"
CANCELLED_TEXT = "❌ 已取消 Cancelled"


# ========= 共用工具 =========

def _tz_now() -> datetime:
    """台北時間 now（作為時間比較用）"""
    os.environ.setdefault("TZ", "Asia/Taipei")
    try:
        time.tzset()
    except Exception:
        pass
    return datetime.now()


def _tz_now_str() -> str:
    """台北時間 now 的字串（寫回表格用）"""
    t = _tz_now()
    return t.strftime("%Y-%m-%d %H:%M:%S")


def _time_hm_from_any(s: str) -> str:
    """把 '18:30', '2025/12/08 18:30', '18：30' 等轉成 'HH:MM'。"""
    s = (s or "").strip().replace("：", ":")
    if " " in s and ":" in s:
        return s.split()[-1][:5]
    if ":" in s:
        return s[:5]
    return s


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


def open_ws(name: str) -> gspread.Worksheet:
    credentials, _ = google.auth.default(scopes=SCOPES)
    gc = gspread.authorize(credentials)
    sh = gc.open_by_key(SPREADSHEET_ID)
    return sh.worksheet(name)


def _sheet_headers(ws: gspread.Worksheet, header_row: int) -> List[str]:
    headers = ws.row_values(header_row)
    return [(h or "").strip() for h in headers]


def header_map_main(ws: gspread.Worksheet) -> Dict[str, int]:
    """
    依表頭名稱建立 map：欄名 -> 欄 index (1-based)。
    e.g. {"主班次時間": 19, "預約編號": 3, ...}
    """
    row = _sheet_headers(ws, HEADER_ROW_MAIN)
    m: Dict[str, int] = {}
    for idx, name in enumerate(row, start=1):
        if name and name not in m:
            m[name] = idx
    return m


def _read_all_rows(ws: gspread.Worksheet) -> List[List[str]]:
    """整張表一次抓回 List[List[str]]。"""
    return ws.get_all_values()


def _find_booking_row(values: List[List[str]],
                      hmap: Dict[str, int],
                      booking_id: str) -> Optional[int]:
    """
    找到指定預約編號所在的「工作表列號」（1-based）。
    """
    col = hmap.get("預約編號")
    if not col:
        return None
    ci = col - 1
    # values[0] -> row1, values[HEADER_ROW_MAIN] -> row3
    for i, row in enumerate(values[HEADER_ROW_MAIN:], start=HEADER_ROW_MAIN + 1):
        if ci < len(row) and (row[ci] or "").strip() == booking_id:
            return i
    return None


def _safe_int(v: Any, default: int = 0) -> int:
    try:
        s = str(v).strip()
        if not s:
            return default
        # 有些會是 1.0 之類
        return int(float(s))
    except Exception:
        return default


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


# ========= FastAPI App =========

app = FastAPI(title="Shuttle Driver API", version="2.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:8080",
        "http://127.0.0.1:8080",
        # 未來可加上正式前端網域
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health():
    return {"status": "ok", "time": _tz_now_str()}


# ========= 1. 班次列表（主班次時間） =========

@app.get("/api/driver/trips", response_model=List[DriverTrip])
def driver_get_trips():
    """
    司機用：取得未來「主班次時間」的班次列表。
    等價於你原本 Sheet 裡的：
      FILTER( 主班次時間 >= NOW()-1/24 ) 再 UNIQUE + 拆成日期/時間。
    """
    ws = open_ws(SHEET_NAME_MAIN)
    hmap = header_map_main(ws)
    values = _read_all_rows(ws)

    if "主班次時間" not in hmap:
        # 主班次時間一定要存在
        return []

    idx_main_dt = hmap["主班次時間"] - 1
    idx_pax_col = hmap.get("確認人數", hmap.get("預約人數", 0))
    idx_pax = idx_pax_col - 1 if idx_pax_col else None
    idx_status_col = hmap.get("預約狀態")
    idx_status = idx_status_col - 1 if idx_status_col else None

    now = _tz_now()
    cutoff = now - timedelta(hours=1)  # NOW() - 1/24

    trips_by_dt: Dict[str, DriverTrip] = {}

    for row in values[HEADER_ROW_MAIN:]:
        if not any(row):
            continue
        if idx_main_dt >= len(row):
            continue

        main_raw = (row[idx_main_dt] or "").strip()
        if not main_raw:
            continue

        # 排除已取消（包含 ❌ 的都跳過）
        if idx_status is not None and idx_status < len(row):
            st = (row[idx_status] or "").strip()
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

        if idx_pax is not None and idx_pax < len(row):
            trips_by_dt[main_raw].total_pax += _safe_int(row[idx_pax], 0)

    return sorted(trips_by_dt.values(), key=lambda t: (t.date, t.time))


# ========= 2. 指定班次乘客列表（依站點） =========

@app.get("/api/driver/trip_passengers", response_model=List[DriverPassenger])
def driver_get_trip_passengers(
    trip_id: str = Query(..., description="主班次時間原始字串，例如 2025/12/08 18:30")
):
    """
    司機用：取得指定「主班次時間」班次的乘客清單。
    一位乘客拆成「上車」與「下車」兩筆（用於 App 站點分組畫面）。
    """
    ws = open_ws(SHEET_NAME_MAIN)
    hmap = header_map_main(ws)
    values = _read_all_rows(ws)

    if "主班次時間" not in hmap:
        return []

    idx_main_dt = hmap["主班次時間"] - 1

    idx_booking = hmap.get("預約編號", 0) - 1
    idx_name = hmap.get("姓名", 0) - 1
    idx_phone = hmap.get("手機", 0) - 1
    idx_room = hmap.get("房號", 0) - 1
    idx_pax_col = hmap.get("確認人數", hmap.get("預約人數", 0))
    idx_pax = idx_pax_col - 1 if idx_pax_col else None
    idx_pick = hmap.get("上車地點", 0) - 1
    idx_drop = hmap.get("下車地點", 0) - 1
    idx_status = hmap.get("乘車狀態", 0) - 1
    idx_dir = hmap.get("往返", 0) - 1
    idx_qr = hmap.get("QRCode編碼", 0) - 1

    result: List[DriverPassenger] = []

    for row in values[HEADER_ROW_MAIN:]:
        if not any(row):
            continue
        if idx_main_dt >= len(row):
            continue

        main_raw = (row[idx_main_dt] or "").strip()
        if main_raw != trip_id:
            continue

        booking_id = (row[idx_booking] if 0 <= idx_booking < len(row) else "").strip()
        name = (row[idx_name] if 0 <= idx_name < len(row) else "").strip()
        phone = (row[idx_phone] if 0 <= idx_phone < len(row) else "").strip()
        room = (row[idx_room] if 0 <= idx_room < len(row) else "").strip()
        ride_status = (row[idx_status] if 0 <= idx_status < len(row) else "").strip()
        qrcode = (row[idx_qr] if 0 <= idx_qr < len(row) else "").strip()
        direction = (row[idx_dir] if 0 <= idx_dir < len(row) else "").strip()

        pax = 1
        if idx_pax is not None and 0 <= idx_pax < len(row):
            pax = _safe_int(row[idx_pax], 1)

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
                    status=ride_status,
                    direction=direction,
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
                    status=ride_status,
                    direction=direction,
                    qrcode=qrcode,
                )
            )

    def sort_key(p: DriverPassenger):
        # 站點字串前面有 1️⃣ 2️⃣...，字面排序就會是正確順序
        return (p.station, 0 if p.updown == "上車" else 1, p.booking_id)

    return sorted(result, key=sort_key)


# ========= 3. 乘客清單（全部班次、照出車總覽公式） =========

@app.get("/api/driver/passenger_list", response_model=List[DriverAllPassenger])
def driver_get_passenger_list():
    """
    司機 / 主管用：乘客總清單。
    完整模擬你在 Sheet 中那條「出車總覽」 ARRAYFORMULA + QUERY 的邏輯：
      - data 來源：預約審核(櫃台)
      - 用 主班次時間 >= NOW() 做篩選
      - 排除含「❌」的預約狀態
      - 依 主班次時間、往返、stationSort、dropoff_order 排序
      - 輸出欄位：車次、主班次時間、預約編號、乘車狀態、往返、
                  姓名、手機、房號、確認人數、
                  飯店(去)、捷運站、火車站、LaLaport、飯店(回)
    """
    ws = open_ws(SHEET_NAME_MAIN)
    hmap = header_map_main(ws)
    values = _read_all_rows(ws)

    # 需要用到的欄位索引
    def col_idx(name: str) -> int:
        return hmap.get(name, 0) - 1

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
        if idx_main_dt < 0 or idx_main_dt >= len(row):
            continue

        main_raw = (row[idx_main_dt] or "").strip()
        if not main_raw:
            continue

        dt = _parse_main_dt(main_raw)
        if not dt or dt < now:
            # 只有主班次時間 >= NOW 的才保留
            continue

        status_val = (row[idx_status] if 0 <= idx_status < len(row) else "").strip()
        if "❌" in status_val:
            # 排除已取消
            continue

        rid = (row[idx_rid] if 0 <= idx_rid < len(row) else "").strip()
        car_raw = (row[idx_car_raw] if 0 <= idx_car_raw < len(row) else "").strip()
        direction = (row[idx_dir] if 0 <= idx_dir < len(row) else "").strip()
        up = (row[idx_up] if 0 <= idx_up < len(row) else "").strip()
        down = (row[idx_down] if 0 <= idx_down < len(row) else "").strip()
        name = (row[idx_name] if 0 <= idx_name < len(row) else "").strip()
        phone_raw = (row[idx_phone] if 0 <= idx_phone < len(row) else "").strip()
        room_raw = (row[idx_room] if 0 <= idx_room < len(row) else "").strip()
        qty_raw = (row[idx_qty] if 0 <= idx_qty < len(row) else "").strip()
        ride_status = (row[idx_ride] if 0 <= idx_ride < len(row) else "").strip()

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
    booking_id = parts[1].strip()
    if not booking_id:
        return DriverCheckinResponse(
            status="error",
            message="QRCode 內容缺少預約編號",
        )

    ws = open_ws(SHEET_NAME_MAIN)
    hmap = header_map_main(ws)
    values = _read_all_rows(ws)

    if "預約編號" not in hmap:
        raise HTTPException(500, "主表缺少『預約編號』欄位")

    rowno = _find_booking_row(values, hmap, booking_id)
    if rowno is None:
        return DriverCheckinResponse(
            status="not_found",
            message=f"找不到預約編號 {booking_id}",
        )

    # 直接從 values 取值，避免多次 cell() 呼叫
    row_idx = rowno - 1  # values 的 index
    row = values[row_idx] if 0 <= row_idx < len(values) else []

    def getv(col_name: str) -> str:
        ci = hmap.get(col_name, 0) - 1
        if ci < 0 or ci >= len(row):
            return ""
        return row[ci] or ""

    # 更新乘車狀態 / 最後操作時間
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

    # 回傳給前端顯示
    pax_str = getv("確認人數") or getv("預約人數") or "1"
    pax = _safe_int(pax_str, 1)

    return DriverCheckinResponse(
        status="success",
        message="已完成上車紀錄",
        booking_id=booking_id,
        name=getv("姓名"),
        pax=pax,
        station=getv("上車地點"),
    )
