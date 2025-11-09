# booking-manager/server.py
import os
from typing import Dict, Any, List
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import gspread
from google.oauth2.service_account import Credentials
from google.auth import default as google_auth_default
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

SPREADSHEET_ID = os.getenv("SPREADSHEET_ID", "1xp54tKOczklmT8uacW-HMxwV8r0VOR2ui33jYcE2pUQ")
ORDERS_SHEET_NAME = os.getenv("ORDERS_SHEET_NAME", "預約審核(櫃台)")

app = FastAPI(title="Hotel Shuttle - Booking Manager API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

def _gspread_client():
    sa_json = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON")
    scopes = ["https://www.googleapis.com/auth/spreadsheets"]
    if sa_json:
        creds = Credentials.from_service_account_info(eval(sa_json), scopes=scopes)
        return gspread.authorize(creds)
    creds, _ = google_auth_default(scopes=scopes)
    return gspread.authorize(creds)

def _open_orders_ws():
    gc = _gspread_client()
    sh = gc.open_by_key(SPREADSHEET_ID)
    try:
        return sh.worksheet(ORDERS_SHEET_NAME)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"無法開啟工作表：{ORDERS_SHEET_NAME}, {e}")

def header_map(ws) -> Dict[str, int]:
    headers = ws.row_values(1)
    return {h: i for i, h in enumerate(headers)}

def _get_value(row: List[str], hmap: Dict[str,int], key: str) -> str:
    if key not in hmap:
        return ""
    idx = hmap[key]
    return row[idx] if idx < len(row) else ""

def _within_one_month(date_str: str) -> bool:
    # 支援 2025/11/6 或 2025-11-06
    if not date_str:
        return False
    try:
        if "-" in date_str:
            dt = datetime.strptime(date_str, "%Y-%m-%d")
        else:
            dt = datetime.strptime(date_str, "%Y/%m/%d")
    except Exception:
        # 若日期在「車次」欄
        try:
            # e.g. '11/9 21:00'
            short = date_str.strip().lstrip("'")
            m = int(short.split()[0].split("/")[0])
            d = int(short.split()[0].split("/")[1])
            now = datetime.now(ZoneInfo("Asia/Taipei"))
            dt = datetime(year=now.year, month=m, day=d)
        except Exception:
            return False
    now = datetime.now(ZoneInfo("Asia/Taipei"))
    return dt >= now - timedelta(days=31)

@app.post("/api/query-orders")
def query_orders(payload: Dict[str, Any]):
    ws = _open_orders_ws()
    hmap = header_map(ws)
    rows = ws.get_all_values()

    booking_id = (payload.get("booking_id") or "").strip()
    phone = (payload.get("phone") or "").strip()
    email = (payload.get("email") or "").strip()

    if not booking_id and not phone and not email:
        raise HTTPException(status_code=400, detail="請至少提供 booking_id、phone、email 其中之一")

    out = []
    for r in rows[1:]:
        # 篩選條件
        rid = _get_value(r, hmap, "預約編號").strip()
        rphone = _get_value(r, hmap, "手機").strip()
        remail = _get_value(r, hmap, "信箱").strip()
        if booking_id:
            cond = (rid == booking_id)
        elif phone:
            cond = (rphone == phone)
        else:
            cond = (remail.lower() == email.lower())
        if not cond:
            continue

        # 一個月內
        if not _within_one_month(_get_value(r, hmap, "日期")):
            continue

        record = {
            "預約編號": rid,
            "申請日期": _get_value(r, hmap, "申請日期"),
            "乘車狀態": _get_value(r, hmap, "乘車狀態"),
            "姓名": _get_value(r, hmap, "姓名"),
            "手機": rphone,
            "信箱": remail,
            "往返": _get_value(r, hmap, "往返"),
            "日期": _get_value(r, hmap, "日期"),
            "車次": _get_value(r, hmap, "車次"),
            "上車地點": _get_value(r, hmap, "上車地點"),
            "下車地點": _get_value(r, hmap, "下車地點"),
            "預約人數": _get_value(r, hmap, "預約人數"),
            "確認人數": _get_value(r, hmap, "確認人數"),
            "櫃台審核": _get_value(r, hmap, "櫃台審核"),
            "備註": _get_value(r, hmap, "備註"),
            "上車索引": _get_value(r, hmap, "上車索引"),
            "下車索引": _get_value(r, hmap, "下車索引"),
            "涉及路段範圍": _get_value(r, hmap, "涉及路段範圍"),
            "QR編碼": _get_value(r, hmap, "QR編碼"),
        }
        out.append(record)

    return out

def _find_row_by_booking_id(ws, booking_id: str) -> int:
    values = ws.col_values(1)  # 假設「預約編號」在第一欄？不安全，改用標題尋找
    headers = ws.row_values(1)
    if "預約編號" in headers:
        col_idx = headers.index("預約編號") + 1
        col_vals = ws.col_values(col_idx)
        for i, v in enumerate(col_vals[1:], start=2):
            if v.strip() == booking_id:
                return i
    # 若找不到
    return -1

def _set_cell_by_header(ws, row_idx: int, hmap: Dict[str,int], key: str, value: str):
    if key not in hmap:
        return
    col = hmap[key] + 1
    ws.update_cell(row_idx, col, value)

def _now_str():
    tz = ZoneInfo("Asia/Taipei")
    dt = datetime.now(tz)
    return f"{dt.year}/{dt.month}/{dt.day} {dt.hour:02d}:{dt.minute:02d}"

@app.post("/api/update-order")
def update_order(payload: Dict[str, Any]):
    """
    以 booking_id 更新：日期、車次、上/下車地點、預約人數 等。
    """
    booking_id = (payload.get("booking_id") or "").strip()
    if not booking_id:
        raise HTTPException(status_code=400, detail="缺少 booking_id")
    ws = _open_orders_ws()
    row_idx = _find_row_by_booking_id(ws, booking_id)
    if row_idx < 0:
        raise HTTPException(status_code=404, detail="查無此預約")

    hmap = header_map(ws)
    # 更新欄位
    if payload.get("date"):
        ws.update_cell(row_idx, hmap["日期"] + 1, payload["date"])
    if payload.get("time") and payload.get("date"):
        short = payload["time"]
        # 強制純文字 M/D HH:MM
        try:
            y, m, d = payload["date"].split("-")
            text = f"'{int(m)}/{int(d)} {short}"
        except Exception:
            text = f"'{payload['date']} {short}"
        ws.update_cell(row_idx, hmap["車次"] + 1, text)
    if payload.get("pickLocation"):
        ws.update_cell(row_idx, hmap["上車地點"] + 1, payload["pickLocation"])
    if payload.get("dropLocation"):
        ws.update_cell(row_idx, hmap["下車地點"] + 1, payload["dropLocation"])
    if payload.get("passengers"):
        ws.update_cell(row_idx, hmap["預約人數"] + 1, str(payload["passengers"]))

    # 更新索引與區間
    def station_index(name: str, role: str) -> int:
        if "福泰" in name or "Forte Hotel" in name:
            return 1 if role == "pickup" else 5
        if "展覽" in name or "MRT Exit 3" in name or "Exhibition" in name:
            return 2
        if "火車" in name or "Train" in name:
            return 3
        if "LaLaport" in name or "LaLa" in name or "Shopping" in name:
            return 4
        return 3
    def involved_segments(pick_idx: int, drop_idx: int) -> str:
        if pick_idx >= drop_idx:
            rng = list(range(min(pick_idx, drop_idx), max(pick_idx, drop_idx)))
        else:
            rng = list(range(pick_idx, drop_idx))
        return ",".join(str(x) for x in rng)

    pick = payload.get("pickLocation") or ws.cell(row_idx, hmap["上車地點"] + 1).value
    drop = payload.get("dropLocation") or ws.cell(row_idx, hmap["下車地點"] + 1).value

    pidx = station_index(pick, "pickup")
    didx = station_index(drop, "dropoff")
    ws.update_cell(row_idx, hmap["上車索引"] + 1, str(pidx))
    ws.update_cell(row_idx, hmap["下車索引"] + 1, str(didx))
    ws.update_cell(row_idx, hmap["涉及路段範圍"] + 1, involved_segments(pidx, didx))

    # 寫入 V 欄位類型的修改紀錄（以表頭搜尋）
    for key in ["操作紀錄", "修改記錄", "變更記錄"]:
        if key in hmap:
            ws.update_cell(row_idx, hmap[key] + 1, f"{_now_str()} 已修改")
            break

    return {"status": "success"}

@app.post("/api/delete-order")
def delete_order(payload: Dict[str, Any]):
    booking_id = (payload.get("booking_id") or "").strip()
    if not booking_id:
        raise HTTPException(status_code=400, detail="缺少 booking_id")
    ws = _open_orders_ws()
    row_idx = _find_row_by_booking_id(ws, booking_id)
    if row_idx < 0:
        raise HTTPException(status_code=404, detail="查無此預約")
    hmap = header_map(ws)
    if "預約狀態" in hmap:
        ws.update_cell(row_idx, hmap["預約狀態"] + 1, "已刪除")
    for key in ["操作紀錄", "修改記錄", "變更記錄"]:
        if key in hmap:
            ws.update_cell(row_idx, hmap[key] + 1, f"{_now_str()} 已刪除")
            break
    return {"status": "success"}

@app.post("/api/checkin")
def checkin(payload: Dict[str, Any]):
    """
    APP 掃碼後呼叫：以 QR 編碼找單，將「乘車狀態」標記為「已上車」
    payload: {"qr": "FORTEXIZHI|1109001"}
    """
    qr = (payload.get("qr") or "").strip()
    if not qr:
        raise HTTPException(status_code=400, detail="缺少 qr")
    ws = _open_orders_ws()
    hmap = header_map(ws)
    if "QR編碼" not in hmap:
        raise HTTPException(status_code=400, detail="工作表缺少欄位：QR編碼")

    col_vals = ws.col_values(hmap["QR編碼"] + 1)
    row_idx = -1
    for i, v in enumerate(col_vals[1:], start=2):
        if v.strip() == qr:
            row_idx = i
            break
    if row_idx < 0:
        raise HTTPException(status_code=404, detail="查無 QR 訂單")

    if "乘車狀態" in hmap:
        ws.update_cell(row_idx, hmap["乘車狀態"] + 1, "已上車")
    for key in ["操作紀錄", "修改記錄", "變更記錄"]:
        if key in hmap:
            ws.update_cell(row_idx, hmap[key] + 1, f"{_now_str()} 已上車")
            break

    return {"status": "success"}
