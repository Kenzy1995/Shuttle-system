# Hotel-shuttle-system/booking-api/server.py
# FastAPI for public booking: create/query/modify/delete
# Sheet: 預約審核(櫃台)
# New column D: 乘車狀態  -> default 未上車; scanning app will set 已上車
#
# Env:
#   GOOGLE_APPLICATION_CREDENTIALS   -> service account JSON path
#   BOOKINGS_SHEET_ID                -> Google Sheet ID (default to provided id)
#   BOOKINGS_SHEET_TAB               -> Worksheet title (default 預約審核(櫃台))
#   SCHEDULE_SHEET_ID / SCHEDULE_SHEET_TAB (optional) for capacity updates

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional, List, Dict, Any, Tuple
import os, io, re, base64
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import gspread
from google.oauth2.service_account import Credentials
import qrcode

TZ = ZoneInfo("Asia/Taipei")

# Defaults wired to your sheet id and tab
BOOKINGS_SHEET_ID = os.getenv("BOOKINGS_SHEET_ID", "1xp54tKOczklmT8uacW-HMxwV8r0VOR2ui33jYcE2pUQ").strip()
BOOKINGS_SHEET_TAB = os.getenv("BOOKINGS_SHEET_TAB", "預約審核(櫃台)").strip() or "預約審核(櫃台)"

SCHEDULE_SHEET_ID = os.getenv("SCHEDULE_SHEET_ID", "").strip()
SCHEDULE_SHEET_TAB = os.getenv("SCHEDULE_SHEET_TAB", "Schedule").strip() or "Schedule"

# ----- Google Sheets helpers -----
def get_gc() -> gspread.Client:
    cred_path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
    if not cred_path or not os.path.exists(cred_path):
        raise RuntimeError("GOOGLE_APPLICATION_CREDENTIALS not set or file not found.")
    creds = Credentials.from_service_account_file(cred_path, scopes=[
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive"
    ])
    return gspread.authorize(creds)

def open_ws(sheet_id: str, tab: str) -> gspread.Worksheet:
    gc = get_gc()
    sh = gc.open_by_key(sheet_id)
    try:
        return sh.worksheet(tab)
    except gspread.WorksheetNotFound:
        return sh.add_worksheet(title=tab, rows="1000", cols="60")

def read_all(ws: gspread.Worksheet):
    vals = ws.get_all_values()
    if not vals: return [], []
    return vals[0], vals[1:]

def header_index_map(headers: List[str]) -> Dict[str, int]:
    return {h: i for i, h in enumerate(headers)}

def ensure_column(ws: gspread.Worksheet, headers: List[str], name: str):
    if name not in headers:
        ws.update_cell(1, len(headers)+1, name)
        headers.append(name)

def update_row_raw(ws: gspread.Worksheet, row_idx_1: int, values: List[Any]):
    rng = gspread.utils.rowcol_to_a1(row_idx_1, 1) + ":" + gspread.utils.rowcol_to_a1(row_idx_1, len(values))
    ws.update(rng, [values], value_input_option="RAW")

# ----- Domain helpers -----
def now_ts_str() -> str:
    d = datetime.now(TZ)
    return f"{d.year}/{d.month}/{d.day} {d.hour:02d}:{d.minute:02d}"  # YYYY/M/D HH:MM

def hm_norm(hm: str) -> str:
    s = hm.strip().replace("：", ":")
    hh, mm = s.split(":")[:2]
    return f"{int(hh):02d}:{int(mm):02d}"

def schedule_text(ymd: str, hm: str) -> str:
    m = int(ymd[5:7]); d = int(ymd[8:10]); hm2 = hm_norm(hm)
    return f"'{m}/{d} {hm2}"  # pure text

def mmdd(ymd: str) -> str:
    return f"{int(ymd[5:7]):02d}{int(ymd[8:10]):02d}"

def gen_booking_id(ws, ymd: str) -> str:
    headers, rows = read_all(ws)
    H = header_index_map(headers)
    seq = 0
    if rows and "預約編號" in H and "日期" in H:
        for r in rows:
            if len(r) > H["日期"] and r[H["日期"]] == ymd and re.fullmatch(r"\d{7}", (r[H["預約編號"]] or "")):
                seq += 1
    seq += 1
    return f"{mmdd(ymd)}{seq:03d}"

def station_index(name: str, role: str) -> int:
    s = (name or "").strip()
    if any(k in s for k in ["福泰大飯店", "Forte Hotel"]):
        return 1 if role == "pick" else 5
    if any(k in s for k in ["捷運", "MRT", "Exhibition"]): return 2
    if any(k in s for k in ["火車", "Train"]): return 3
    if any(k in s for k in ["LaLaport", "Lalaport", "LaLaPort"]): return 4
    return 2

def involved_segments(up_idx: int, down_idx: int) -> str:
    if down_idx <= up_idx: return ""
    return ",".join(str(i) for i in range(up_idx, down_idx))

def gen_qr_png_data_url(text: str) -> str:
    qr = qrcode.QRCode(version=1, box_size=6, border=1)
    qr.add_data(text)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode("ascii")

def adjust_capacity(ymd: str, hm: str, direction: str, station: str, delta: int):
    if not SCHEDULE_SHEET_ID: return
    ws = open_ws(SCHEDULE_SHEET_ID, SCHEDULE_SHEET_TAB)
    headers, rows = read_all(ws)
    H = header_index_map(headers)
    need = ["日期","班次","去程 / 回程","站點","可預約人數"]
    if not all(k in H for k in need): return
    for i, r in enumerate(rows, start=2):
        if (r[H["日期"]] == ymd and hm_norm(r[H["班次"]]) == hm and
            r[H["去程 / 回程"]].strip()==direction and r[H["站點"]].strip()==station):
            try: avail = int(re.sub(r"\D","", r[H["可預約人數"]]))
            except: avail = 0
            ws.update_cell(i, H["可預約人數"]+1, str(max(0, avail + delta)))
            break

# ----- Models -----
class BookPayload(BaseModel):
    direction: str
    date: str           # YYYY-MM-DD
    station: str        # 外站名（站點）
    time: str           # HH:MM
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

class ModifyPayload(BookPayload):
    booking_id: str

class DeletePayload(BaseModel):
    booking_id: str

class QueryPayload(BaseModel):
    booking_id: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None

# ----- App -----
app = FastAPI(title="Hotel Shuttle Booking API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"],
)

@app.get("/api/healthz")
def healthz(): return {"ok": True}

def ensure_headers(ws):
    must = [
        "預約編號","申請日期","日期","車次","往返",
        "上車地點","下車地點","姓名","手機","信箱",
        "預約人數","確認人數","上車索引","下車索引","涉及路段範圍",
        "乘車狀態","預約狀態","櫃台審核","備註","修改紀錄","QR編碼"
    ]
    headers, _ = read_all(ws)
    if not headers:
        ws.update("A1", [must])
        headers = must[:]
    else:
        for h in must:
            ensure_column(ws, headers, h)
    return headers

@app.post("/api/book")
def api_book(p: BookPayload):
    ws = open_ws(BOOKINGS_SHEET_ID, BOOKINGS_SHEET_TAB)
    headers = ensure_headers(ws); H = header_index_map(headers)

    ymd = p.date; hm = hm_norm(p.time)
    bid = gen_booking_id(ws, ymd)
    ts = now_ts_str()
    up = station_index(p.pickLocation if p.direction=="回程" else "福泰大飯店 Forte Hotel", "pick")
    down = station_index("福泰大飯店 Forte Hotel" if p.direction=="回程" else p.dropLocation, "drop")
    segs = involved_segments(up, down)

    qr_code_value = bid  # 編碼內容 = 預約編號
    qr_img = gen_qr_png_data_url(qr_code_value)

    row = [""]*len(headers)
    def setv(k, v): row[H[k]] = v

    setv("預約編號", bid)
    setv("申請日期", ts)
    setv("日期", ymd)
    setv("車次", schedule_text(ymd, hm))
    setv("往返", p.direction)
    setv("上車地點", p.pickLocation if p.direction=="回程" else "福泰大飯店 Forte Hotel")
    setv("下車地點", "福泰大飯店 Forte Hotel" if p.direction=="回程" else p.dropLocation)
    setv("姓名", p.name); setv("手機", p.phone); setv("信箱", p.email)
    setv("預約人數", str(p.passengers)); setv("確認人數", str(p.passengers))
    setv("上車索引", str(up)); setv("下車索引", str(down)); setv("涉及路段範圍", segs)
    setv("乘車狀態", "未上車")
    setv("預約狀態", "已預約")
    setv("櫃台審核", "")
    setv("備註", ""); setv("修改紀錄", "")
    setv("QR編碼", qr_code_value)

    ws.append_row(row, value_input_option="RAW")

    try:
        adjust_capacity(ymd, hm, p.direction, p.station, -p.passengers)
    except Exception as e:
        print("[WARN] capacity adjust:", e)

    return {"status":"success", "booking_id": bid, "qr_url": qr_img}

@app.post("/api/query-orders")
def api_query(q: QueryPayload):
    ws = open_ws(BOOKINGS_SHEET_ID, BOOKINGS_SHEET_TAB)
    headers, rows = read_all(ws)
    if not headers: return []
    H = header_index_map(headers)

    def gv(r, k): 
        idx = H.get(k); 
        return r[idx] if idx is not None and idx < len(r) else ""

    now = datetime.now(TZ); month_ago = now - timedelta(days=30)
    out = []
    for r in rows:
        bid = gv(r, "預約編號"); phone = gv(r, "手機"); email = gv(r, "信箱")
        if not any([q.booking_id, q.phone, q.email]): continue
        cond = False
        if q.booking_id and q.booking_id.strip()==bid: cond=True
        if q.phone and q.phone.strip()==phone: cond=True
        if q.email and q.email.strip().lower()==email.lower(): cond=True
        if not cond: continue

        ymd = gv(r, "日期")
        try:
            d = datetime.strptime(ymd, "%Y-%m-%d").replace(tzinfo=TZ)
            if d < month_ago: continue
        except: 
            continue

        car = (gv(r, "車次") or "").lstrip("'")
        m = re.search(r"(\d{1,2}):(\d{2})", car); hm = f"{int(m.group(1)):02d}:{m.group(2)}" if m else ""
        out.append({
            "booking_id": bid,
            "date_ymd": ymd,
            "time_hm": hm,
            "direction": gv(r, "往返"),
            "pick": gv(r, "上車地點"),
            "drop": gv(r, "下車地點"),
            "name": gv(r, "姓名"),
            "phone": phone,
            "email": email,
            "status": gv(r, "預約狀態") or "已預約",
            "audit_status": gv(r, "櫃台審核"),
            "ride_status": gv(r, "乘車狀態") or "未上車",
            "qr_url": gen_qr_png_data_url(gv(r, "QR編碼") or bid)
        })
    return out

@app.post("/api/modify")
def api_modify(p: ModifyPayload):
    ws = open_ws(BOOKINGS_SHEET_ID, BOOKINGS_SHEET_TAB)
    headers, rows = read_all(ws)
    if not headers: raise HTTPException(400, "No data")
    H = header_index_map(headers)

    # locate row
    found_idx = None; old = None
    for i, r in enumerate(rows, start=2):
        if (H.get("預約編號") is not None and r[H["預約編號"]] == p.booking_id):
            found_idx = i; old = r; break
    if not found_idx: raise HTTPException(404, "Booking not found")

    def gv(r, k):
        idx = H.get(k); return r[idx] if idx is not None and idx < len(r) else ""

    # capacity rollback from old
    old_pass = int(re.sub(r"\D","", gv(old,"確認人數") or gv(old,"預約人數") or "0") or 0)
    old_ymd = gv(old, "日期")
    old_hm = ""
    car = (gv(old, "車次") or "").lstrip("'"); m = re.search(r"(\d{1,2}):(\d{2})", car)
    if m: old_hm = f"{int(m.group(1)):02d}:{m.group(2)}"
    old_dir = gv(old, "往返")
    old_station = gv(old, "下車地點") if old_dir!="回程" else gv(old,"上車地點")

    # new values
    ymd = p.date; hm = hm_norm(p.time)
    up = station_index(p.pickLocation if p.direction=="回程" else "福泰大飯店 Forte Hotel", "pick")
    down = station_index("福泰大飯店 Forte Hotel" if p.direction=="回程" else p.dropLocation, "drop")
    segs = involved_segments(up, down)

    newvals = old[:] + [""]*(len(headers)-len(old))
    def setc(k, v): newvals[H[k]] = v

    setc("日期", ymd)
    setc("車次", schedule_text(ymd, hm))
    setc("往返", p.direction)
    setc("上車地點", p.pickLocation if p.direction=="回程" else "福泰大飯店 Forte Hotel")
    setc("下車地點", "福泰大飯店 Forte Hotel" if p.direction=="回程" else p.dropLocation)
    setc("預約人數", str(p.passengers)); setc("確認人數", str(p.passengers))
    setc("上車索引", str(up)); setc("下車索引", str(down)); setc("涉及路段範圍", segs)
    # 乘車狀態不改動，由掃碼流程設定
    setc("修改紀錄", f"{now_ts_str()} 已修改")

    update_row_raw(ws, found_idx, newvals)

    try:
        if old_ymd and old_hm:
            adjust_capacity(old_ymd, old_hm, old_dir, old_station, +old_pass)
        adjust_capacity(ymd, hm, p.direction, p.station, -p.passengers)
    except Exception as e:
        print("[WARN] capacity adjust:", e)

    return {"status":"success", "booking_id": p.booking_id, "qr_url": gen_qr_png_data_url(p.booking_id)}

@app.post("/api/delete")
def api_delete(payload: DeletePayload):
    ws = open_ws(BOOKINGS_SHEET_ID, BOOKINGS_SHEET_TAB)
    headers, rows = read_all(ws)
    if not headers: raise HTTPException(400, "No data")
    H = header_index_map(headers)

    found_idx = None; old = None
    for i, r in enumerate(rows, start=2):
        if (H.get("預約編號") is not None and r[H["預約編號"]] == payload.booking_id):
            found_idx = i; old = r; break
    if not found_idx: raise HTTPException(404, "Booking not found")

    def gv(r, k):
        idx = H.get(k); return r[idx] if idx is not None and idx < len(r) else ""

    passengers = int(re.sub(r"\D","", gv(old,"確認人數") or gv(old,"預約人數") or "0") or 0)
    old_ymd = gv(old, "日期")
    old_hm = ""
    car = (gv(old, "車次") or "").lstrip("'"); m = re.search(r"(\d{1,2}):(\d{2})", car)
    if m: old_hm = f"{int(m.group(1)):02d}:{m.group(2)}"
    old_dir = gv(old, "往返")
    old_station = gv(old, "下車地點") if old_dir!="回程" else gv(old,"上車地點")

    newvals = old[:] + [""]*(len(headers)-len(old))
    newvals[H["預約狀態"]] = "已取消"
    newvals[H["修改紀錄"]] = f"{now_ts_str()} 已取消"
    update_row_raw(ws, found_idx, newvals)

    try:
        if old_ymd and old_hm:
            adjust_capacity(old_ymd, old_hm, old_dir, old_station, +passengers)
    except Exception as e:
        print("[WARN] capacity adjust:", e)

    return {"status":"success"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("server:app", host="0.0.0.0", port=8001, reload=True)
