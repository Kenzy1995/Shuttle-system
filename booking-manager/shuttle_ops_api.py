
"""
shuttle_ops_api.py
FastAPI「寫入與營運」服務（/api/ops）

功能：
- action=book   新增預約
- action=query  查詢預約（可用 booking_id / phone / email 任一條件）
- action=modify 修改預約（更動日期/時間/站點/人數等）
- action=delete 刪除預約（軟刪除，更新狀態與最後操作時間）
- action=check_in 乘車掃碼（將「乘車狀態」設為「已上車」）
- GET /api/qr/{code}   產生 QR 圖片（供前端顯示與下載）

重要：
1) 讀取班次的 API 不在此檔案內，且不需修改（仍為您現有之 Cloud Run /api/sheet ）。
2) 本服務僅負責「預約審核(櫃台)」工作表之新增/查詢/修改/刪除與掃碼。
3) 工作表已插入新欄 D「乘車狀態」。本程式以「標題列名稱」對應欄位，
   不使用 A/B/C… 欄位座標，因此即便新增欄位也不會錯位。
4) 必要環境變數：
   - GOOGLE_SERVICE_ACCOUNT_JSON  指向 service account 憑證 JSON 檔路徑
   - SPREADSHEET_ID               Google 試算表 ID
   - SHEET_NAME                   工作分頁名稱（預設：預約審核(櫃台)）

安裝套件：
    pip install fastapi uvicorn gspread google-auth qrcode pillow

啟動：
    uvicorn shuttle_ops_api:app --host 0.0.0.0 --port 8080 --reload
"""
from __future__ import annotations

import io
import os
import time
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

import qrcode
from fastapi import FastAPI, HTTPException, Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, validator

import gspread
from google.oauth2.service_account import Credentials


# ---------- 常數與工具 ----------

DEFAULT_SHEET_NAME = os.getenv("SHEET_NAME", "預約審核(櫃台)")

# 欄位標題可能的別名（容錯）
HEADER_ALIASES = {
    "申請日期": {"申請日期", "建立時間", "建立日期", "建立日期時間", "created_at", "Created At"},
    "最後操作時間": {"最後操作時間", "最後更新時間", "V欄位", "updated_at", "Updated At"},
    "預約編號": {"預約編號", "訂單編號", "booking_id", "Booking ID"},
    "往返": {"往返", "方向", "direction"},
    "日期": {"日期", "Date", "出發日期"},
    "班次": {"班次", "時間", "出發時間", "Schedule"},
    "車次": {"車次", "顯示車次", "顯示時間", "顯示日期時間"},
    "上車地點": {"上車地點", "上車站點", "上車", "Pickup Station", "Pickup"},
    "下車地點": {"下車地點", "下車站點", "下車", "Dropoff Station", "Dropoff"},
    "姓名": {"姓名", "name", "Name"},
    "手機": {"手機", "電話", "Phone"},
    "信箱": {"信箱", "Email", "email"},
    "預約人數": {"預約人數", "人數", "Passengers"},
    "櫃台審核": {"櫃台審核", "審核", "U欄位", "audit", "Audit"},
    "預約狀態": {"預約狀態", "狀態", "Status"},
    "乘車狀態": {"乘車狀態", "乘車", "已上車", "Board Status"},
    "身分": {"身分", "身分類型", "identity"},
    "房號": {"房號", "Room", "Room Number"},
    "入住日期": {"入住日期", "CheckIn", "Check-in Date"},
    "退房日期": {"退房日期", "CheckOut", "Check-out Date"},
    "用餐日期": {"用餐日期", "Dining Date"},
    "上車索引": {"上車索引", "PickupIndex"},
    "下車索引": {"下車索引", "DropIndex"},
    "涉及路段範圍": {"涉及路段範圍", "Segments"},
    "QRCode編碼": {"QRCode編碼", "QR內容", "QR Code", "QRCode", "QR碼編碼", "QR"},
}

# 站點（請依實際文案調整，含別名與正規化）
STOP_ALIASES = {
    "福泰大飯店": {"福泰大飯店", "Forte Hotel", "Forte Hotel Xizhi", "福泰大飯店 Forte Hotel"},
    "南港展覽館-捷運3號出口": {
        "南港展覽館-捷運3號出口",
        "南港展覽館捷運站",
        "Nangang Exhibition Center - MRT Exit 3",
        "南港展覽館捷運站 Nangang Exhibition Center - MRT Exit 3",
        "南港展覽館捷運站 Exit 3",
    },
    "南港火車站": {"南港火車站", "Nangang Train Station", "南港火車站 Nangang Train Station"},
    "南港 LaLaport Shopping Park": {"南港 LaLaport Shopping Park", "LaLaport", "南港 LaLaport"},
}

# 環狀路線索引：去程：飯店=1  -> 展館=2 -> 火車=3 -> LaLaport=4 -> 飯店=5
ROUTE_ORDER = [
    "福泰大飯店",
    "南港展覽館-捷運3號出口",
    "南港火車站",
    "南港 LaLaport Shopping Park",
    "福泰大飯店",
]


def _normalize_stop(name: str) -> str:
    """將站名正規化為上述四個主鍵之一。"""
    raw = (name or "").strip()
    for key, aliases in STOP_ALIASES.items():
        if raw in aliases:
            return key
        # 寬鬆包含
        for a in aliases:
            if raw.lower() == a.lower():
                return key
    # 無法辨識就原文
    return raw


def _tz_now_str() -> str:
    """台北時區現在時間字串 yyyy/m/d HH:MM"""
    # 不引入 pytz，採用 time.localtime 配置 TZ。部署請將環境變數 TZ=Asia/Taipei
    try:
        os.environ.setdefault("TZ", "Asia/Taipei")
        time.tzset()  # type: ignore[attr-defined]
    except Exception:
        pass
    t = time.localtime()
    return f"{t.tm_year}/{t.tm_mon}/{t.tm_mday} {t.tm_hour:02d}:{t.tm_min:02d}"


def _display_trip_str(date_iso: str, time_hm: str) -> str:
    """回傳「M/D HH:MM」純文字。前置單引號，避免 Sheets 自動轉日期。"""
    y, m, d = date_iso.split("-")
    m = str(int(m))
    d = str(int(d))
    return f"'%s/%s %s" % (m, d, time_hm)


def _time_hm_from_any(s: str) -> str:
    s = (s or "").strip().replace("：", ":")
    if " " in s and ":" in s:
        # 可能 YYYY-MM-DD HH:MM 或 M/D HH:MM
        hm = s.split()[-1]
        return hm[:5]
    if ":" in s:
        return s[:5]
    return s


def _compute_indices_and_segments(direction: str, pickup: str, dropoff: str):
    """回傳 (pickup_idx, drop_idx, segments_str) 如 '1,2'。
    規則：去程時，飯店為 1；回程時，飯店為 5。
    涉及路段為 [min, max-1]，不含下車站。
    """
    norm_pick = _normalize_stop(pickup)
    norm_drop = _normalize_stop(dropoff)

    def base_index(stop: str) -> int:
        # 在環狀路線中的位置（1~5）
        for i, s in enumerate(ROUTE_ORDER, start=1):
            if stop == s:
                return i
        # 不在既定清單則回傳 0
        return 0

    pick_idx = base_index(norm_pick)
    drop_idx = base_index(norm_drop)

    # 特例：去程的飯店應為 1，回程的飯店應為 5
    if norm_pick == "福泰大飯店" and direction == "去程":
        pick_idx = 1
    if norm_drop == "福泰大飯店" and direction == "回程":
        drop_idx = 5

    lo = min(pick_idx, drop_idx)
    hi = max(pick_idx, drop_idx)
    segments = [str(i) for i in range(lo, max(lo, hi) )]  # 到 hi-1
    if segments and segments[-1] == str(hi):
        segments = segments[:-1]
    # 若 pick=drop 或無法辨識，segments 會為空
    seg_str = ",".join(segments)
    return pick_idx, drop_idx, seg_str


def _mmdd_prefix(date_iso: str) -> str:
    y, m, d = date_iso.split("-")
    return f"{int(m):02d}{int(d):02d}"


# ---------- Google Sheets ----------

def open_sheet() -> gspread.Worksheet:
    json_path = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON")
    if not json_path or not os.path.exists(json_path):
        raise RuntimeError("找不到 GOOGLE_SERVICE_ACCOUNT_JSON 指定的憑證檔")

    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]
    credentials = Credentials.from_service_account_file(json_path, scopes=scopes)
    gc = gspread.authorize(credentials)

    spreadsheet_id = os.getenv("SPREADSHEET_ID")
    if not spreadsheet_id:
        raise RuntimeError("請設定環境變數 SPREADSHEET_ID")

    sh = gc.open_by_key(spreadsheet_id)
    ws = sh.worksheet(os.getenv("SHEET_NAME", DEFAULT_SHEET_NAME))
    return ws


def header_map(ws: gspread.Worksheet) -> Dict[str, int]:
    """回傳 {標準標題: 1-based column index}"""
    row = ws.row_values(1)
    m: Dict[str, int] = {}
    for idx, name in enumerate(row, start=1):
        name = (name or "").strip()
        if not name:
            continue
        for std, aliases in HEADER_ALIASES.items():
            if name == std or name in aliases:
                # 若同義字重複，以首個為準
                if std not in m:
                    m[std] = idx
    return m


def _read_all_rows(ws: gspread.Worksheet) -> List[List[str]]:
    return ws.get_all_values()


def _find_rows_by_pred(ws: gspread.Worksheet, pred) -> List[int]:
    """回傳符合條件的資料列號清單（>=2）"""
    values = _read_all_rows(ws)
    if not values:
        return []
    headers = values[0]
    result_rows: List[int] = []
    for i in range(1, len(values)):
        row = values[i]
        row_dict = {headers[j]: row[j] if j < len(row) else "" for j in range(len(headers))}
        if pred(row_dict):
            result_rows.append(i + 1)  # 1-based with header row at 1
    return result_rows


def _get_max_seq_for_date(ws: gspread.Worksheet, date_iso: str) -> int:
    """找出同一天已有的最大序號，ID 格式 mmddNNN"""
    m = header_map(ws)
    all_values = _read_all_rows(ws)
    if not all_values:
        return 0
    headers = all_values[0]
    try:
        c_id = m["預約編號"]
    except KeyError:
        return 0
    prefix = _mmdd_prefix(date_iso)
    max_seq = 0
    for i in range(1, len(all_values)):
        row = all_values[i]
        booking = row[c_id - 1] if c_id - 1 < len(row) else ""
        if booking.startswith(prefix):
            tail = booking[len(prefix):]
            try:
                seq = int(tail)
                max_seq = max(max_seq, seq)
            except ValueError:
                continue
    return max_seq


# ---------- Pydantic 參數 ----------

class BookPayload(BaseModel):
    direction: str
    date: str              # YYYY-MM-DD
    station: str
    time: str              # HH:MM
    identity: str          # hotel / dining
    checkIn: Optional[str] = None  # YYYY-MM-DD
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
        v = (v or "").strip()
        if v not in {"去程", "回程"}:
            raise ValueError("方向僅允許 去程 / 回程")
        return v


class QueryPayload(BaseModel):
    booking_id: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None


class ModifyPayload(BaseModel):
    booking_id: str
    # 以下皆為可選擇性修改
    direction: Optional[str] = None
    date: Optional[str] = None           # YYYY-MM-DD
    station: Optional[str] = None
    time: Optional[str] = None           # HH:MM
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

app = FastAPI(title="Shuttle Ops API", version="1.0.0")

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


@app.get("/api/qr/{code}")
def qr_image(code: str):
    """產生 QR 圖片（PNG）。code 即為寫入欄位的 QRCode 編碼內容。"""
    img = qrcode.make(code)
    bio = io.BytesIO()
    img.save(bio, format="PNG")
    return Response(content=bio.getvalue(), media_type="image/png")


def _ensure_headers(ws: gspread.Worksheet) -> Dict[str, int]:
    m = header_map(ws)
    required = [
        "申請日期", "最後操作時間", "預約編號", "往返", "日期",
        "班次", "車次", "上車地點", "下車地點", "姓名", "手機", "信箱",
        "預約人數", "櫃台審核", "預約狀態", "乘車狀態", "身分",
        "房號", "入住日期", "退房日期", "用餐日期",
        "上車索引", "下車索引", "涉及路段範圍", "QRCode編碼",
    ]
    missing = [k for k in required if k not in m]
    if missing:
        raise HTTPException(status_code=400, detail=f"工作表缺少欄位：{', '.join(missing)}")
    return m


def _row_dict(headers: List[str], row: List[str]) -> Dict[str, str]:
    return {headers[i]: (row[i] if i < len(row) else "") for i in range(len(headers))}


@app.post("/api/ops")
def ops(req: OpsRequest):
    action = (req.action or "").strip().lower()
    data = req.data or {}

    ws = open_sheet()
    hmap = _ensure_headers(ws)

    if action == "book":
        p = BookPayload(**data)

        # 產生預約編號：mmdd + 連號（3位）
        last_seq = _get_max_seq_for_date(ws, p.date)
        seq = last_seq + 1
        booking_id = f"{_mmdd_prefix(p.date)}{seq:03d}"

        # 顯示車次（純文字）
        car_display = _display_trip_str(p.date, _time_hm_from_any(p.time))

        # 計算索引與路段
        pickup = p.pickLocation
        dropoff = p.dropLocation
        pk_idx, dp_idx, seg_str = _compute_indices_and_segments(p.direction, pickup, dropoff)

        # QR 內容：可自由調整。此處包含 booking id
        qr_content = f"FORTEXZ:{booking_id}"

        values = _read_all_rows(ws)
        headers = values[0] if values else []
        # 新增資料列
        newrow = [""] * len(headers)

        def setv(col_name: str, v: str):
            idx = hmap[col_name] - 1
            if idx >= 0 and idx < len(newrow):
                newrow[idx] = str(v)

        setv("申請日期", _tz_now_str())
        setv("最後操作時間", "")
        setv("預約編號", booking_id)
        setv("往返", p.direction)
        setv("日期", p.date)  # 保留 ISO 以利後端篩選
        setv("班次", _time_hm_from_any(p.time))
        setv("車次", car_display)  # 'M/D HH:MM 純文字
        setv("上車地點", pickup)
        setv("下車地點", dropoff)
        setv("姓名", p.name)
        setv("手機", p.phone)
        setv("信箱", p.email)
        setv("預約人數", str(p.passengers))
        setv("櫃台審核", "")
        setv("預約狀態", "已預約")
        setv("乘車狀態", "")
        setv("身分", "住宿貴賓" if p.identity == "hotel" else "用餐貴賓")
        setv("房號", p.roomNumber or "")
        setv("入住日期", p.checkIn or "")
        setv("退房日期", p.checkOut or "")
        setv("用餐日期", p.diningDate or "")
        setv("上車索引", str(pk_idx if pk_idx else ""))
        setv("下車索引", str(dp_idx if dp_idx else ""))
        setv("涉及路段範圍", seg_str)
        setv("QRCode編碼", qr_content)

        ws.append_row(newrow, value_input_option="USER_ENTERED")

        return {
            "status": "success",
            "booking_id": booking_id,
            "qr_url": f"/api/qr/{qr_content}",
        }

    elif action == "query":
        p = QueryPayload(**data)
        if not (p.booking_id or p.phone or p.email):
            raise HTTPException(status_code=400, detail="至少提供 booking_id / phone / email 其中一項")

        all_values = _read_all_rows(ws)
        if not all_values:
            return []

        headers = all_values[0]
        now = datetime.now()
        one_month_ago = now - timedelta(days=31)
        results: List[Dict[str, Any]] = []

        def get(row, key, default=""):
            if key not in hmap:
                return default
            idx = hmap[key] - 1
            return row[idx] if idx < len(row) else default

        for i in range(1, len(all_values)):
            row = all_values[i]
            # 一個月內：依「日期」（ISO）比對
            date_iso = get(row, "日期", "")
            try:
                d = datetime.strptime(date_iso, "%Y-%m-%d")
            except Exception:
                # 若無法解析，直接略過時效限制
                d = now
            if d < one_month_ago:
                continue

            # 條件比對
            bid = get(row, "預約編號", "")
            ph = get(row, "手機", "")
            em = get(row, "信箱", "")
            if p.booking_id and p.booking_id != bid:
                continue
            if p.phone and p.phone != ph:
                continue
            if p.email and p.email != em:
                continue

            item = {
                "申請日期": get(row, "申請日期", ""),
                "預約編號": bid,
                "往返": get(row, "往返", ""),
                "日期": date_iso,
                "班次": get(row, "班次", ""),
                "車次": get(row, "車次", ""),
                "上車地點": get(row, "上車地點", ""),
                "下車地點": get(row, "下車地點", ""),
                "姓名": get(row, "姓名", ""),
                "手機": ph,
                "信箱": em,
                "預約人數": get(row, "預約人數", ""),
                "櫃台審核": get(row, "櫃台審核", ""),
                "預約狀態": get(row, "預約狀態", ""),
                "乘車狀態": get(row, "乘車狀態", ""),
                "QRCode編碼": get(row, "QRCode編碼", ""),
            }
            results.append(item)
        return results

    elif action == "modify":
        p = ModifyPayload(**data)
        target_rows = _find_rows_by_pred(ws, lambda r: r.get("預約編號", "") == p.booking_id)
        if not target_rows:
            raise HTTPException(status_code=404, detail="找不到此預約編號")

        rowno = target_rows[0]
        values = _read_all_rows(ws)
        headers = values[0]
        row = values[rowno - 1]

        # 取原資料，用來補空白
        def cur(key: str) -> str:
            idx = hmap[key] - 1
            return row[idx] if idx < len(row) else ""

        direction = p.direction or cur("往返")
        date_iso = p.date or cur("日期")
        time_hm = p.time or cur("班次")
        pick = p.pickLocation or cur("上車地點")
        drop = p.dropLocation or cur("下車地點")
        passengers = str(p.passengers) if p.passengers else cur("預約人數")

        car_display = _display_trip_str(date_iso, _time_hm_from_any(time_hm))
        pk_idx, dp_idx, seg_str = _compute_indices_and_segments(direction, pick, drop)

        updates = {
            "最後操作時間": _tz_now_str() + " 已修改",
            "往返": direction,
            "日期": date_iso,
            "班次": _time_hm_from_any(time_hm),
            "車次": car_display,
            "上車地點": pick,
            "下車地點": drop,
            "預約人數": passengers,
            "上車索引": str(pk_idx if pk_idx else ""),
            "下車索引": str(dp_idx if dp_idx else ""),
            "涉及路段範圍": seg_str,
            "預約狀態": "已預約",  # 保持已預約狀態
        }

        cell_list = []
        for k, v in updates.items():
            c = hmap[k]
            cell_list.append(gspread.Cell(row=rowno, col=c, value=v))
        ws.update_cells(cell_list, value_input_option="USER_ENTERED")

        return {"status": "success", "booking_id": p.booking_id}

    elif action == "delete":
        p = DeletePayload(**data)
        target_rows = _find_rows_by_pred(ws, lambda r: r.get("預約編號", "") == p.booking_id)
        if not target_rows:
            raise HTTPException(status_code=404, detail="找不到此預約編號")
        rowno = target_rows[0]
        updates = {
            "最後操作時間": _tz_now_str() + " 已刪除",
            "預約狀態": "已刪除",
        }
        cell_list = [gspread.Cell(row=rowno, col=hmap[k], value=v) for k, v in updates.items()]
        ws.update_cells(cell_list, value_input_option="USER_ENTERED")
        return {"status": "success", "booking_id": p.booking_id}

    elif action == "check_in":
        p = CheckInPayload(**data)
        if not (p.code or p.booking_id):
            raise HTTPException(status_code=400, detail="需提供 code 或 booking_id")

        def predicate(r):
            if p.booking_id:
                return r.get("預約編號", "") == p.booking_id
            # 以 QRCode 編碼比對
            return r.get("QRCode編碼", "") == (p.code or "")

        target_rows = _find_rows_by_pred(ws, predicate)
        if not target_rows:
            raise HTTPException(status_code=404, detail="找不到符合條件之訂單")
        rowno = target_rows[0]

        updates = {
            "最後操作時間": _tz_now_str() + " 已上車",
            "乘車狀態": "已上車",
        }
        cell_list = [gspread.Cell(row=rowno, col=hmap[k], value=v) for k, v in updates.items()]
        ws.update_cells(cell_list, value_input_option="USER_ENTERED")
        return {"status": "success", "row": rowno}

    else:
        raise HTTPException(status_code=400, detail=f"未知 action：{action}")
