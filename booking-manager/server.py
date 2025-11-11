# server_batch.py
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Any, Dict, List, Optional
import io
import os
import time
import json
import hashlib
from datetime import datetime, timedelta

# Google Sheets
import gspread
from google.auth import default as google_auth_default
from gspread.utils import rowcol_to_a1

# QR
try:
    import qrcode
except ImportError:
    qrcode = None

SPREADSHEET_NAME = os.getenv("BOOKING_SPREADSHEET_NAME", "Shuttle-Bookings")
WORKSHEET_NAME = os.getenv("BOOKING_WORKSHEET_NAME", "orders")
SCHEDULE_SHEET_NAME = os.getenv("SCHEDULE_SHEET_NAME", "schedule")  # 可選，用於座位數調整
BASE_PATH = os.getenv("BASE_PATH", "")  # 反向代理時可設定 "/api"
QR_ROUTE_PREFIX = os.getenv("QR_ROUTE_PREFIX", "/api/qr")

# 欄位名稱（與前端查詢需求對齊）
FIELD_BOOKING_ID = "預約編號"
FIELD_DATE = "日期"
FIELD_TIME = "班次"
FIELD_TRIP = "往返"
FIELD_PICK = "上車地點"
FIELD_DROP = "下車地點"
FIELD_NAME = "姓名"
FIELD_PHONE = "手機"
FIELD_EMAIL = "信箱"
FIELD_PAX = "預約人數"
FIELD_STATUS = "預約狀態"
FIELD_AUDIT = "櫃台審核"
FIELD_BOARD = "乘車狀態"
FIELD_QR = "QRCode編碼"
FIELD_STATION = "站點"

# 預設表頭順序
DEFAULT_HEADERS = [
    FIELD_BOOKING_ID, FIELD_DATE, FIELD_TIME, FIELD_TRIP,
    FIELD_PICK, FIELD_DROP, FIELD_STATION,
    FIELD_NAME, FIELD_PHONE, FIELD_EMAIL, FIELD_PAX,
    FIELD_STATUS, FIELD_AUDIT, FIELD_BOARD, FIELD_QR,
    "created_at", "updated_at"
]

app = FastAPI(title="Hotel Shuttle Ops (batch)")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _client():
    creds, _ = google_auth_default(scopes=["https://www.googleapis.com/auth/spreadsheets"])
    return gspread.authorize(creds)


def _open_ws(gc=None):
    if gc is None:
        gc = _client()
    ss = gc.open(SPREADSHEET_NAME)
    ws = ss.worksheet(WORKSHEET_NAME)
    return ss, ws


def _headers(ws) -> List[str]:
    values = ws.row_values(1)
    return values if values else DEFAULT_HEADERS[:]


def _load_records(ws) -> List[Dict[str, Any]]:
    rows = ws.get_all_values()
    if not rows:
        return []
    headers = rows[0]
    out: List[Dict[str, Any]] = []
    for r in rows[1:]:
        if not any(col.strip() for col in r):
            continue
        item = {}
        for i, h in enumerate(headers):
            item[h] = r[i] if i < len(r) else ""
        out.append(item)
    return out


def _index_by_id(records: List[Dict[str, Any]]) -> Dict[str, int]:
    # 回傳預約編號 -> row_index_in_sheet (2-based data row -> 1 header, so row = idx+2)
    idx = {}
    for i, r in enumerate(records, start=2):
        bid = str(r.get(FIELD_BOOKING_ID, "")).strip()
        if bid:
            idx[bid] = i
    return idx


def _gen_booking_id(date_iso: str) -> str:
    # yyyymmdd + short entropy
    stamp = datetime.utcnow().strftime("%Y%m%d%H%M%S")
    seed = f"{date_iso}-{stamp}-{os.urandom(4).hex()}"
    short = hashlib.sha1(seed.encode()).hexdigest()[:6].upper()
    return f"{datetime.utcnow().strftime('%m%d')}{short}"


def _ensure_headers(ws, headers: List[str]):
    current = _headers(ws)
    if current == headers:
        return
    # 擴充缺少的表頭在尾端，不破壞既有欄位
    updates = current[:]
    for h in headers:
        if h not in updates:
            updates.append(h)
    # 寫回第一列
    rng = f"A1:{rowcol_to_a1(1, len(updates))}"
    ws.batch_update([{"range": rng, "values": [updates]}], value_input_option="RAW")


def _get_base_url(request: Request) -> str:
    # 組合 QR 端點絕對 URL
    base = str(request.base_url).rstrip("/")
    if BASE_PATH:
        base = base + BASE_PATH
    return base


class OpsEnvelope(BaseModel):
    action: str
    data: Optional[Dict[str, Any]] = None


@app.post("/api/ops")
async def ops(req: Request, env: OpsEnvelope):
    gc = _client()
    ss, ws = _open_ws(gc)

    # 確保表頭齊全
    _ensure_headers(ws, DEFAULT_HEADERS)
    headers = _headers(ws)

    # 載入一次，後續所有操作在記憶體處理，最後 batch_update
    records = _load_records(ws)
    id_index = _index_by_id(records)

    action = (env.action or "").lower()
    data = env.data or {}

    if action == "query":
        # 篩選：booking_id 或 phone 或 email 三擇一
        bid = str(data.get("booking_id", "")).strip()
        phone = str(data.get("phone", "")).strip()
        email = str(data.get("email", "")).strip()
        if not (bid or phone or email):
            return JSONResponse([])

        def match(r: Dict[str, Any]) -> bool:
            if bid and str(r.get(FIELD_BOOKING_ID, "")).strip() == bid:
                return True
            if phone and phone in str(r.get(FIELD_PHONE, "")):
                return True
            if email and email.lower() == str(r.get(FIELD_EMAIL, "")).lower():
                return True
            return False

        results = [r for r in records if match(r)]
        return JSONResponse(results)

    elif action == "book":
        # 單次新增，單次寫入
        date = str(data.get("date", "")).strip()
        time_s = str(data.get("time", "")).strip()
        rb = str(data.get("direction", "")).strip()  # 去程/回程
        station = str(data.get("station", "")).strip()
        pick = str(data.get("pickLocation", "")).strip()
        drop = str(data.get("dropLocation", "")).strip()
        name = str(data.get("name", "")).strip()
        phone = str(data.get("phone", "")).strip()
        email = str(data.get("email", "")).strip()
        pax = int(data.get("passengers", 1))

        if not (date and time_s and rb and pick and drop and name and phone and email and pax > 0):
            raise HTTPException(400, "缺少必要欄位")

        booking_id = _gen_booking_id(date)
        qr_payload = json.dumps({"booking_id": booking_id, "date": date, "time": time_s}, ensure_ascii=False)

        # 準備一列資料
        now = datetime.utcnow().isoformat(timespec="seconds")
        row_obj = {h: "" for h in headers}
        row_obj.update({
            FIELD_BOOKING_ID: booking_id,
            FIELD_DATE: date,
            FIELD_TIME: time_s,
            FIELD_TRIP: rb,
            FIELD_PICK: pick,
            FIELD_DROP: drop,
            FIELD_STATION: station,
            FIELD_NAME: name,
            FIELD_PHONE: phone,
            FIELD_EMAIL: email,
            FIELD_PAX: str(pax),
            FIELD_STATUS: "已預約",
            FIELD_AUDIT: "Y",
            FIELD_BOARD: "",
            FIELD_QR: qr_payload,
            "created_at": now,
            "updated_at": now,
        })

        # 寫入一次：append_row
        values = [row_obj.get(h, "") for h in headers]
        ws.append_row(values, value_input_option="RAW")

        base = _get_base_url(req)
        qr_url = f"{base}{QR_ROUTE_PREFIX}/{qrcode_quote(qr_payload)}"
        return JSONResponse({"status": "success", "booking_id": booking_id, "qr_url": qr_url})

    elif action == "modify":
        # 查找並一次性更新該 row
        booking_id = str(data.get("booking_id", "")).strip()
        if not booking_id:
            raise HTTPException(400, "booking_id 缺失")

        row_idx = id_index.get(booking_id)
        if not row_idx:
            raise HTTPException(404, "找不到該預約")

        # 更新可改欄位
        updates: Dict[str, Any] = {}
        for key, field in [
            ("date", FIELD_DATE),
            ("time", FIELD_TIME),
            ("direction", FIELD_TRIP),
            ("pickLocation", FIELD_PICK),
            ("dropLocation", FIELD_DROP),
            ("station", FIELD_STATION),
            ("phone", FIELD_PHONE),
            ("email", FIELD_EMAIL),
            ("passengers", FIELD_PAX),
        ]:
            if key in data and data[key] is not None:
                updates[field] = str(data[key])

        if not updates:
            return JSONResponse({"status": "success", "booking_id": booking_id})

        updates["updated_at"] = datetime.utcnow().isoformat(timespec="seconds")

        # 批次寫回整列
        row = ws.row_values(row_idx)
        if not row:
            row = [""] * len(headers)
        else:
            # 擴充避免超界
            if len(row) < len(headers):
                row += [""] * (len(headers) - len(row))

        for h, v in updates.items():
            try:
                j = headers.index(h)
                row[j] = v
            except ValueError:
                continue

        rng = f"A{row_idx}:{rowcol_to_a1(row_idx, len(headers))}"
        ws.batch_update([{"range": rng, "values": [row]}], value_input_option="RAW")
        return JSONResponse({"status": "success", "booking_id": booking_id})

    elif action == "delete" or action == "cancel":
        booking_id = str(data.get("booking_id", "")).strip()
        if not booking_id:
            raise HTTPException(400, "booking_id 缺失")

        row_idx = id_index.get(booking_id)
        if not row_idx:
            raise HTTPException(404, "找不到該預約")

        # 單次寫入：把狀態標記為取消，清除 QR
        row = ws.row_values(row_idx)
        if len(row) < len(headers):
            row += [""] * (len(headers) - len(row))

        def set_field(field: str, value: str):
            try:
                j = headers.index(field)
            except ValueError:
                return
            row[j] = value

        set_field(FIELD_STATUS, "已取消")
        set_field(FIELD_QR, "")
        set_field("updated_at", datetime.utcnow().isoformat(timespec="seconds"))

        rng = f"A{row_idx}:{rowcol_to_a1(row_idx, len(headers))}"
        ws.batch_update([{"range": rng, "values": [row]}], value_input_option="RAW")
        return JSONResponse({"status": "success", "booking_id": booking_id})

    else:
        raise HTTPException(400, f"未知 action: {action}")


def qrcode_quote(s: str) -> str:
    # URL-safe quote w/o importing urllib to keep deps minimal
    return "".join([
        c if c.isalnum() or c in "-_.~" else "%{:02X}".format(ord(c))
        for c in s
    ])


@app.get(f"{QR_ROUTE_PREFIX}" + "/{payload}")
def qr_image(payload: str):
    # 解碼百分比編碼
    try:
        # 簡易解碼
        from urllib.parse import unquote
        text = unquote(payload)
    except Exception:
        text = payload

    if qrcode is None:
        # 若無 qrcode 套件，回傳 1x1 透明 PNG，避免前端崩潰
        buf = io.BytesIO()
        buf.write(
            bytes.fromhex(
                "89504E470D0A1A0A0000000D49484452000000010000000108060000001F15C4890000000A49444154789C6360000002000154A24F2A0000000049454E44AE426082"
            )
        )
        buf.seek(0)
        return StreamingResponse(buf, media_type="image/png")

    img = qrcode.make(text)
    out = io.BytesIO()
    img.save(out, format="PNG")
    out.seek(0)
    return StreamingResponse(out, media_type="image/png")


@app.get("/healthz")
def healthz():
    return {"ok": True}


# 本地開發可：uvicorn server_batch:app --reload --port 8000
