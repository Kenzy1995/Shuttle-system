# booking-manager/server.py
import os, io, json, base64, re
from typing import Dict, Any, List, Optional
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import gspread
from google.oauth2.service_account import Credentials
from google.auth import default as google_auth_default
import qrcode

TZ = ZoneInfo("Asia/Taipei")
SPREADSHEET_ID = os.getenv("SPREADSHEET_ID", "1xp54tKOczklmT8uacW-HMxwV8r0VOR2ui33jYcE2pUQ")
ORDERS_SHEET_NAME = os.getenv("ORDERS_SHEET_NAME", "預約審核(櫃台)")

app = FastAPI(title="Booking Manager API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], allow_methods=["*"], allow_headers=["*"],
)

def _gspread_client() -> gspread.Client:
    sa_json = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON")
    scopes = ["https://www.googleapis.com/auth/spreadsheets"]
    if sa_json:
        info = json.loads(sa_json)
        creds = Credentials.from_service_account_info(info, scopes=scopes)
        return gspread.authorize(creds)
    creds, _ = google_auth_default(scopes=scopes)
    return gspread.authorize(creds)

def _open_orders_ws() -> gspread.Worksheet:
    gc = _gspread_client()
    sh = gc.open_by_key(SPREADSHEET_ID)
    try:
        return sh.worksheet(ORDERS_SHEET_NAME)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"無法開啟工作表：{ORDERS_SHEET_NAME}, {e}")

def now_ts() -> str:
    d = datetime.now(TZ)
    return f"{d.year}/{d.month}/{d.day} {d.hour:02d}:{d.minute:02d}"

def hm_norm(hm: str) -> str:
    s = (hm or "").strip().replace("：", ":")
    hh, mm = s.split(":")[:2]
    return f"{int(hh):02d}:{int(mm):02d}"

def schedule_text(ymd: str, hm: str) -> str:
    y, m, d = ymd.split("-")
    return f"'{int(m)}/{int(d)} {hm_norm(hm)}"

def ensure_headers(ws) -> Dict[str, int]:
    headers = ws.row_values(1)
    header_map = {h: i for i, h in enumerate(headers)}
    required = [
        "預約編號","申請日期","乘車狀態","姓名","手機","信箱",
        "往返","日期","車次","上車地點","下車地點","預約人數",
        "確認人數","櫃台審核","備註","上車索引","下車索引",
        "涉及路段範圍","QR編碼","操作紀錄","預約狀態"
    ]
    changed = False
    for h in required:
        if h not in header_map:
            headers.append(h)
            header_map[h] = len(headers) - 1
            changed = True
    if changed:
        ws.update('1:1', [headers])
    return header_map

def gen_booking_id(ws, ymd: str) -> str:
    headers = ws.row_values(1)
    try:
        idx = headers.index("預約編號")
    except ValueError:
        idx = -1
    prefix = f"{int(ymd[5:7]):02d}{int(ymd[8:10]):02d}"  # MMDD
    rows = ws.get_all_values()
    max_seq = 0
    if idx >= 0:
        for r in rows[1:]:
            if idx < len(r):
                bid = (r[idx] or "").strip()
                if bid.startswith(prefix):
                    tail = bid[len(prefix):]
                    try:
                        n = int(tail[-3:])
                        if n > max_seq: max_seq = n
                    except: pass
    return f"{prefix}{max_seq+1:03d}"

def station_index(name: str, role: str) -> int:
    s = (name or "").strip()
    if "福泰" in s or "Forte Hotel" in s:
        return 1 if role == "pickup" else 5
    if "展覽" in s or "MRT" in s or "Exhibition" in s:
        return 2
    if "火車" in s or "Train" in s:
        return 3
    if "LaLaport" in s or "LaLa" in s:
        return 4
    return 3

def involved_segments(up_idx: int, down_idx: int) -> str:
    if down_idx <= up_idx: return ""
    return ",".join(str(i) for i in range(up_idx, down_idx))

def qr_png_data_uri(text: str) -> str:
    qr = qrcode.QRCode(version=1, box_size=6, border=1)
    qr.add_data(text)
    qr.make(fit=True)
    img = qr.make_image()
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode("ascii")

class BookPayload(BaseModel):
    direction: str
    date: str          # YYYY-MM-DD
    station: str
    time: str          # HH:MM
    identity: Optional[str] = None
    checkIn: Optional[str] = None
    checkOut: Optional[str] = None
    diningDate: Optional[str] = None
    roomNumber: Optional[str] = None
    name: str
    phone: str
    email: str
    passengers: int
    dropLocation: str
    pickLocation: str

class ModifyPayload(BaseModel):
    booking_id: str
    direction: str
    date: str
    time: str
    pickLocation: str
    dropLocation: str
    passengers: int

class DeletePayload(BaseModel):
    booking_id: str

class QueryPayload(BaseModel):
    booking_id: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None

@app.post("/api/book")
def api_book(p: BookPayload):
    ws = _open_orders_ws()
    H = ensure_headers(ws)
    bid = gen_booking_id(ws, p.date)
    ts = now_ts()
    up = station_index(p.pickLocation, "pickup")
    down = station_index(p.dropLocation, "dropoff")
    segs = involved_segments(up, down)
    qr_text = bid
    qr_data_uri = qr_png_data_uri(qr_text)

    # 準備一列
    row = [""] * (max(H.values()) + 1)
    def setv(k, v): row[H[k]] = v

    setv("預約編號", bid)
    setv("申請日期", ts)
    setv("乘車狀態", "未上車")
    setv("姓名", p.name); setv("手機", p.phone); setv("信箱", p.email)
    setv("往返", p.direction)
    setv("日期", p.date)
    setv("車次", schedule_text(p.date, p.time))
    setv("上車地點", p.pickLocation); setv("下車地點", p.dropLocation)
    setv("預約人數", str(p.passengers)); setv("確認人數", str(p.passengers))
    setv("櫃台審核", ""); setv("備註", "")
    setv("上車索引", str(up)); setv("下車索引", str(down)); setv("涉及路段範圍", segs)
    setv("QR編碼", qr_text); setv("操作紀錄", ""); setv("預約狀態", "已預約")

    ws.append_row(row, value_input_option="RAW")
    return {"status": "success", "booking_id": bid, "qr_url": qr_data_uri}

@app.post("/api/query-orders")
def api_query(q: QueryPayload):
    ws = _open_orders_ws()
    headers = ws.row_values(1)
    rows = ws.get_all_values()[1:]
    H = {h:i for i,h in enumerate(headers)}

    def gv(r, k):
        i = H.get(k); return r[i] if i is not None and i < len(r) else ""

    now = datetime.now(TZ); month_ago = now - timedelta(days=30)
    out = []
    for r in rows:
        bid, phone, email = gv(r,"預約編號"), gv(r,"手機"), gv(r,"信箱")
        if q.booking_id and q.booking_id.strip() != bid: 
            pass
        elif q.phone and q.phone.strip() != phone:
            pass
        elif q.email and q.email.strip().lower() != email.lower():
            pass
        elif not any([q.booking_id, q.phone, q.email]):
            continue
        else:
            ymd = gv(r,"日期")
            try:
                d = datetime.strptime(ymd, "%Y-%m-%d").replace(tzinfo=TZ)
                if d < month_ago: 
                    continue
            except:
                continue
            # 取 HH:MM
            car = (gv(r,"車次") or "").lstrip("'")
            m = re.search(r"(\d{1,2}):(\d{2})", car)
            hm = f"{int(m.group(1)):02d}:{m.group(2)}" if m else ""
            out.append({
                "預約編號": bid,
                "日期": ymd,
                "車次": hm,
                "往返": gv(r,"往返"),
                "上車地點": gv(r,"上車地點"),
                "下車地點": gv(r,"下車地點"),
                "姓名": gv(r,"姓名"),
                "手機": phone,
                "信箱": email,
                "預約狀態": gv(r,"預約狀態") or "已預約",
                "櫃台審核": gv(r,"櫃台審核"),
                "乘車狀態": gv(r,"乘車狀態") or "未上車",
                "QR編碼": gv(r,"QR編碼") or bid
            })
    return out

@app.post("/api/modify")
def api_modify(p: ModifyPayload):
    ws = _open_orders_ws()
    headers = ws.row_values(1)
    H = {h:i for i,h in enumerate(headers)}
    values = ws.get_all_values()
    target_row = None
    for idx, r in enumerate(values[1:], start=2):
        if H.get("預約編號") is not None and H["預約編號"] < len(r) and r[H["預約編號"]] == p.booking_id:
            target_row = idx
            break
    if not target_row:
        raise HTTPException(404, "Booking not found")

    row = values[target_row-1] + [""]*(len(headers)-len(values[target_row-1]))
    def setv(k, v): row[H[k]] = v
    setv("日期", p.date)
    setv("車次", schedule_text(p.date, p.time))
    setv("往返", p.direction)
    setv("上車地點", p.pickLocation)
    setv("下車地點", p.dropLocation)
    setv("預約人數", str(p.passengers))
    setv("確認人數", str(p.passengers))
    setv("操作紀錄", f"{now_ts()} 已修改")
    a1_from = gspread.utils.rowcol_to_a1(target_row, 1)
    a1_to   = gspread.utils.rowcol_to_a1(target_row, len(row))
    ws.update(f"{a1_from}:{a1_to}", [row], value_input_option="RAW")
    return {"status": "success", "booking_id": p.booking_id}

@app.post("/api/delete")
def api_delete(p: DeletePayload):
    ws = _open_orders_ws()
    headers = ws.row_values(1)
    H = {h:i for i,h in enumerate(headers)}
    values = ws.get_all_values()
    target_row = None
    for idx, r in enumerate(values[1:], start=2):
        if H.get("預約編號") is not None and H["預約編號"] < len(r) and r[H["預約編號"]] == p.booking_id:
            target_row = idx
            break
    if not target_row:
        raise HTTPException(404, "Booking not found")

    row = values[target_row-1] + [""]*(len(headers)-len(values[target_row-1]))
    row[H["預約狀態"]] = "已取消"
    row[H["操作紀錄"]] = f"{now_ts()} 已取消"
    a1_from = gspread.utils.rowcol_to_a1(target_row, 1)
    a1_to   = gspread.utils.rowcol_to_a1(target_row, len(row))
    ws.update(f"{a1_from}:{a1_to}", [row], value_input_option="RAW")
    return {"status": "success"}
