
from __future__ import annotations
import io
import os
import re
import time
import base64
import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple
import urllib.parse

import qrcode
from fastapi import FastAPI, HTTPException, Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, validator
import gspread
import google.auth
import hashlib

# gmail
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders
try:
    from googleapiclient.discovery import build  # type: ignore
    _GMAIL_AVAILABLE = True
except Exception:
    _GMAIL_AVAILABLE = False

# ========== 日誌設定 ==========
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("booking-manager")

# ========== 常數與工具 ==========
SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
    "https://www.googleapis.com/auth/gmail.send",  # 寄信
]

SPREADSHEET_ID = "1xp54tKOczklmT8uacW-HMxwV8r0VOR2ui33jYcE2pUQ"
SHEET_NAME_MAIN = "預約審核(櫃台)"      # 主資料表
SHEET_NAME_CAP  = "可預約班次(web)"     # 剩餘可預約名額（權威來源）

BASE_URL = "https://booking-manager-995728097341.asia-east1.run.app"

EMAIL_FROM_NAME = "汐止福泰大飯店櫃檯"
EMAIL_FROM_ADDR = "fortehotels.shuttle@gmail.com"

# 主表表頭列（1-based）
HEADER_ROW_MAIN = 2

# 狀態
BOOKED_TEXT = "✔️ 已預約 Booked"
CANCELLED_TEXT = "❌ 已取消 Cancelled"

# 主表允許欄位
HEADER_KEYS = {
    "申請日期","最後操作時間","預約編號","往返","日期","班次","車次",
    "上車地點","下車地點","姓名","手機","信箱","預約人數","櫃台審核",
    "預約狀態","乘車狀態","身分","房號","入住日期","退房日期","用餐日期",
    "上車索引","下車索引","涉及路段範圍","QRCode編碼","備註","寄信狀態"
}

# 可預約班次表必要欄位
CAP_REQ_HEADERS = ["去程 / 回程", "日期", "班次", "站點", "可預約人數"]

# 站點索引（精準雙語字串，完全相同才匹配）
PICK_INDEX_MAP_EXACT = {
    "福泰大飯店 Forte Hotel": 1,
    "南港展覽館捷運站 Nangang Exhibition Center - MRT Exit 3": 2,
    "南港火車站 Nangang Train Station": 3,
    "LaLaport Shopping Park": 4,
}
DROP_INDEX_MAP_EXACT = {
    "南港展覽館捷運站 Nangang Exhibition Center - MRT Exit 3": 2,
    "南港火車站 Nangang Train Station": 3,
    "LaLaport Shopping Park": 4,
    "福泰大飯店 Forte Hotel": 5,
}

def _email_hash6(email: str) -> str:
    return hashlib.sha256((email or "").encode("utf-8")).hexdigest()[:6]

def _tz_now_str() -> str:
    os.environ.setdefault("TZ", "Asia/Taipei")
    try:
        time.tzset()
    except Exception:
        pass
    t = time.localtime()
    return f"{t.tm_year:04d}-{t.tm_mon:02d}-{t.tm_mday:02d} {t.tm_hour:02d}:{t.tm_min:02d}:{t.tm_sec:02d}"

def _today_iso_taipei() -> str:
    os.environ.setdefault("TZ", "Asia/Taipei")
    try:
        time.tzset()
    except Exception:
        pass
    t = time.localtime()
    return f"{t.tm_year:04d}-{t.tm_mon:02d}-{t.tm_mday:02d}"

def _time_hm_from_any(s: str) -> str:
    s = (s or "").strip().replace("：", ":")
    if " " in s and ":" in s:
        return s.split()[-1][:5]
    if ":" in s:
        return s[:5]
    return s

def _display_trip_str(date_iso: str, time_hm: str) -> str:
    if not date_iso or not time_hm:
        return ""
    y, m, d = date_iso.split("-")
    return f"'{int(m)}/{int(d)} {time_hm}"

def _mmdd_prefix(date_iso: str) -> str:
    y, m, d = date_iso.split("-")
    return f"{int(m):02d}{int(d):02d}"

def _compute_indices_and_segments(pickup: str, dropoff: str):
    ps = (pickup or "").strip()
    ds = (dropoff or "").strip()
    pick_idx = PICK_INDEX_MAP_EXACT.get(ps, 0)
    drop_idx = DROP_INDEX_MAP_EXACT.get(ds, 0)
    if pick_idx == 0 or drop_idx == 0 or drop_idx <= pick_idx:
        return pick_idx, drop_idx, ""
    segs = list(range(pick_idx, drop_idx))
    seg_str = ",".join(str(i) for i in segs)
    return pick_idx, drop_idx, seg_str

def _normalize_station_for_capacity(direction: str, pick: str, drop: str) -> str:
    # 可預約班次(web) 的「站點」代表非飯店端的站點
    return (drop if direction == "去程" else pick).strip()

# ========== Google Sheets ==========
def open_ws(name: str) -> gspread.Worksheet:
    try:
        credentials, _ = google.auth.default(scopes=SCOPES)
        gc = gspread.authorize(credentials)
        sh = gc.open_by_key(SPREADSHEET_ID)
        ws = sh.worksheet(name)
        return ws
    except Exception as e:
        raise RuntimeError(f"無法開啟工作表「{name}」: {str(e)}")

def _sheet_headers(ws: gspread.Worksheet, header_row: int) -> List[str]:
    headers = ws.row_values(header_row)
    return [h.strip() for h in headers]

def header_map_main(ws: gspread.Worksheet) -> Dict[str, int]:
    row = _sheet_headers(ws, HEADER_ROW_MAIN)
    m: Dict[str, int] = {}
    for idx, name in enumerate(row, start=1):
        name = (name or "").strip()
        if name in HEADER_KEYS and name not in m:
            m[name] = idx
    return m

def _read_all_rows(ws: gspread.Worksheet) -> List[List[str]]:
    return ws.get_all_values()

def _find_rows_by_pred(ws: gspread.Worksheet, headers: List[str], start_row: int, pred) -> List[int]:
    values = _read_all_rows(ws)
    if not values:
        return []
    hdrs = values[start_row - 1] if len(values) >= start_row else []
    result: List[int] = []
    for i, row in enumerate(values[start_row:], start=start_row + 1):
        if not any(row):
            continue
        d = {hdrs[j]: row[j] if j < len(row) else "" for j in range(len(hdrs))}
        if pred(d):
            result.append(i)
    return result

def _get_max_seq_for_date(ws_main: gspread.Worksheet, date_iso: str) -> int:
    m = header_map_main(ws_main)
    all_values = _read_all_rows(ws_main)
    if not all_values or "預約編號" not in m:
        return 0
    c_id = m["預約編號"]
    prefix = _mmdd_prefix(date_iso)
    max_seq = 0
    for row in all_values[HEADER_ROW_MAIN:]:
        booking = row[c_id - 1] if c_id - 1 < len(row) else ""
        if booking.startswith(prefix):
            try:
                seq = int(booking[len(prefix):])
                max_seq = max(max_seq, seq)
            except:
                pass
    return max_seq

# ========== 可預約班次(web) 解析 ==========
def _find_cap_header_row(values: List[List[str]]) -> int:
    # 在前 5 行內找同時包含「去程 / 回程」與「可預約人數」的列；找不到則回 1
    for i in range(min(5, len(values))):
        row = [c.strip() for c in values[i]]
        if "去程 / 回程" in row and "可預約人數" in row:
            return i + 1  # 1-based
    return 1

def _cap_header_map(values: List[List[str]]) -> Tuple[Dict[str,int], int]:
    hdr_row = _find_cap_header_row(values)
    headers = [c.strip() for c in (values[hdr_row-1] if len(values) >= hdr_row else [])]
    m: Dict[str,int] = {}
    for idx, name in enumerate(headers, start=1):
        if name in CAP_REQ_HEADERS and name not in m:
            m[name] = idx
    return m, hdr_row

def _normalize_text(s: str) -> str:
    return " ".join((s or "").replace("　"," ").split())

def _parse_available(s: str) -> Optional[int]:
    if s is None:
        return None
    m = re.search(r"(\d+)", str(s))
    return int(m.group(1)) if m else None

def lookup_capacity(direction: str, date_iso: str, time_hm: str, station: str) -> int:
    ws_cap = open_ws(SHEET_NAME_CAP)
    values = _read_all_rows(ws_cap)
    m, hdr_row = _cap_header_map(values)
    for key in CAP_REQ_HEADERS:
        if key not in m:
            raise HTTPException(409, f"capacity_header_missing:{key}")

    idx_dir   = m["去程 / 回程"]-1
    idx_date  = m["日期"]-1
    idx_time  = m["班次"]-1
    idx_st    = m["站點"]-1
    idx_avail = m["可預約人數"]-1

    want_dir = _normalize_text(direction)
    want_date = date_iso.strip()
    want_time = _time_hm_from_any(time_hm)
    want_station = _normalize_text(station)

    for row in values[hdr_row:]:
        if not any(row):
            continue
        r_dir   = _normalize_text(row[idx_dir] if idx_dir < len(row) else "")
        r_date  = (row[idx_date] if idx_date < len(row) else "").strip()
        r_time  = _time_hm_from_any(row[idx_time] if idx_time < len(row) else "")
        r_st    = _normalize_text(row[idx_st] if idx_st < len(row) else "")
        r_avail = row[idx_avail] if idx_avail < len(row) else ""

        if r_dir == want_dir and r_date == want_date and r_time == want_time and r_st == want_station:
            avail = _parse_available(r_avail)
            if avail is None:
                raise HTTPException(409, "capacity_not_numeric")
            return avail

    raise HTTPException(409, "capacity_not_found")

# ========== Pydantic ==========
class BookPayload(BaseModel):
    direction: str
    date: str
    station: str
    time: str
    identity: str
    checkIn: Optional[str] = None
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
        if v not in {"去程", "回程"}:
            raise ValueError("方向僅允許 去程 / 回程")
        return v

class QueryPayload(BaseModel):
    booking_id: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None

class ModifyPayload(BaseModel):
    booking_id: str
    direction: Optional[str] = None
    date: Optional[str] = None
    station: Optional[str] = None
    time: Optional[str] = None
    passengers: Optional[int] = Field(None, ge=1, le=4)
    pickLocation: Optional[str] = None
    dropLocation: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None

class DeletePayload(BaseModel):
    booking_id: str

class CheckInPayload(BaseModel):
    code: Optional[str] = None
    booking_id: Optional[str] = None

class MailPayload(BaseModel):
    booking_id: str
    lang: str = Field("zh", pattern="^(zh|en|ja|ko)$")
    kind: str = Field(..., pattern="^(book|modify|cancel)$")
    ticket_png_base64: Optional[str] = None

class OpsRequest(BaseModel):
    action: str
    data: Dict[str, Any]

# ========== Gmail ==========
def _gmail_service():
    if not _GMAIL_AVAILABLE:
        raise RuntimeError("Gmail API 模組不可用（缺少 googleapiclient）")
    credentials, _ = google.auth.default(scopes=SCOPES)
    return build("gmail", "v1", credentials=credentials)

def _send_email_gmail(to_email: str, subject: str, html_body: str, attachment: Optional[bytes] = None, attachment_filename: str = "ticket.png"):
    if not _GMAIL_AVAILABLE:
        raise RuntimeError("Gmail API 未安裝，無法寄信")
    msg = MIMEMultipart()
    msg["To"] = to_email
    msg["From"] = f"{EMAIL_FROM_NAME} <{EMAIL_FROM_ADDR}>"
    msg["Subject"] = subject
    msg.attach(MIMEText(html_body, "html", "utf-8"))
    if attachment:
        part = MIMEBase("application", "octet-stream")
        part.set_payload(attachment)
        encoders.encode_base64(part)
        part.add_header("Content-Disposition", f'attachment; filename="{attachment_filename}"')
        msg.attach(part)
    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode("utf-8")
    svc = _gmail_service()
    svc.users().messages().send(userId="me", body={"raw": raw}).execute()

def _compose_mail_html(info: Dict[str, str], lang: str, kind: str) -> Tuple[str, str]:
    subjects = {
        "book": {
            "zh": "汐止福泰大飯店接駁車預約確認",
            "en": "Forte Hotel Xizhi Shuttle Reservation Confirmation",
            "ja": "汐止フルオンホテル シャトル予約確認",
            "ko": "포르테 호텔 시즈 셔틀 예약 확인",
        },
        "modify": {
            "zh": "汐止福泰大飯店接駁車預約變更確認",
            "en": "Forte Hotel Xizhi Shuttle Reservation Updated",
            "ja": "汐止フルオンホテル シャトル予約変更完了",
            "ko": "포르테 호텔 시즈 셔틀 예약 변경 완료",
        },
        "cancel": {
            "zh": "汐止福泰大飯店接駁車預約已取消",
            "en": "Forte Hotel Xizhi Shuttle Reservation Canceled",
            "ja": "汐止フルオンホテル シャトル予約キャンセル",
            "ko": "포르테 호텔 시즈 셔틀 예약 취소됨",
        },
    }
    subject = f'{subjects[kind]["zh"]} / {subjects[kind].get(lang, subjects[kind]["en"])}'

    zh = f"""
    <div style="color:black">
      <p>尊敬的 {info.get('name','')} 貴賓，您好！</p>
      <p>以下為您的接駁車預約資訊：</p>
      <ul>
        <li>預約編號：{info.get('booking_id','')}</li>
        <li>預約班次：{info.get('date','')} {info.get('time','')} (GMT+8)</li>
        <li>預約人數：{info.get('pax','')}</li>
        <li>往返方向：{info.get('direction','')}</li>
        <li>上車站點：{info.get('pick','')}</li>
        <li>下車站點：{info.get('drop','')}</li>
        <li>手機：{info.get('phone','')}</li>
        <li>信箱：{info.get('email','')}</li>
      </ul>
      <p>如有任何問題，請致電 (02-2691-9222 #1)。</p>
      <p>汐止福泰大飯店 敬上</p>
    </div>
    """
    add_map = {
        "en": f"""
        <div style="color:black">
          <p>Dear {info.get('name','')},</p>
          <p>Here are your shuttle reservation details:</p>
          <ul>
            <li>Reservation Number: {info.get('booking_id','')}</li>
            <li>Reservation Time: {info.get('date','')} {info.get('time','')} (GMT+8)</li>
            <li>Number of Guests: {info.get('pax','')}</li>
            <li>Direction: {info.get('direction','')}</li>
            <li>Pickup: {info.get('pick','')}</li>
            <li>Dropoff: {info.get('drop','')}</li>
            <li>Phone: {info.get('phone','')}</li>
            <li>Email: {info.get('email','')}</li>
          </ul>
          <p>If you have questions, call (02-2691-9222 #1).</p>
          <p>Forte Hotel Xizhi</p>
        </div>
        """,
        "ja": f"""
        <div style="color:black">
          <p>{info.get('name','')} 様</p>
          <p>シャトル予約の詳細は以下の通りです。</p>
          <ul>
            <li>予約番号：{info.get('booking_id','')}</li>
            <li>便：{info.get('date','')} {info.get('time','')} (GMT+8)</li>
            <li>人数：{info.get('pax','')}</li>
            <li>方向：{info.get('direction','')}</li>
            <li>乗車：{info.get('pick','')}</li>
            <li>降車：{info.get('drop','')}</li>
            <li>電話：{info.get('phone','')}</li>
            <li>メール：{info.get('email','')}</li>
          </ul>
          <p>ご不明点は (02-2691-9222 #1) まで。</p>
          <p>汐止フルオンホテル</p>
        </div>
        """,
        "ko": f"""
        <div style="color:black">
          <p>{info.get('name','')} 고객님,</p>
          <p>셔틀 예약 내역은 아래와 같습니다.</p>
          <ul>
            <li>예약번호: {info.get('booking_id','')}</li>
            <li>시간: {info.get('date','')} {info.get('time','')} (GMT+8)</li>
            <li>인원: {info.get('pax','')}</li>
            <li>방향: {info.get('direction','')}</li>
            <li>승차: {info.get('pick','')}</li>
            <li>하차: {info.get('drop','')}</li>
            <li>전화: {info.get('phone','')}</li>
            <li>이메일: {info.get('email','')}</li>
          </ul>
          <p>문의: (02-2691-9222 #1)</p>
          <p>포르테 호텔 시즈</p>
        </div>
        """,
    }
    body = zh + "<br/><br/>" + add_map.get(lang, add_map["en"])
    return subject, body

# ========== FastAPI ==========
app = FastAPI(title="Shuttle Ops API", version="1.4.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://hotel-web-995728097341.asia-east1.run.app",
        "http://127.0.0.1:8080",
        "http://localhost:8080",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/health")
def health():
    return {"status": "ok", "time": _tz_now_str()}

@app.options("/api/ops")
@app.options("/api/ops/")
def ops_options():
    return Response(status_code=204)

# ========== 主 API ==========
@app.post("/api/ops")
@app.post("/api/ops/")
def ops(req: OpsRequest):
    action = (req.action or "").strip().lower()
    data = req.data or {}
    log.info(f"OPS action={action} payload={data}")

    try:
        ws_main = open_ws(SHEET_NAME_MAIN)
        hmap = header_map_main(ws_main)
        headers = _sheet_headers(ws_main, HEADER_ROW_MAIN)

        def setv(row_arr: List[str], col: str, v: Any):
            if col in hmap and 1 <= hmap[col] <= len(row_arr):
                row_arr[hmap[col] - 1] = v if isinstance(v, str) else str(v)

        def get_by_rowno(rowno: int, key: str) -> str:
            if key not in hmap:
                return ""
            return ws_main.cell(rowno, hmap[key]).value or ""

        # ===== 新增預約 =====
        if action == "book":
            p = BookPayload(**data)
            # 容量檢查（可預約班次表是權威：可預約人數 = 現存剩餘數）
            station_for_cap = _normalize_station_for_capacity(p.direction, p.pickLocation, p.dropLocation)
            rem = lookup_capacity(p.direction, p.date, _time_hm_from_any(p.time), station_for_cap)
            if int(p.passengers) > int(rem):
                raise HTTPException(409, f"capacity_exceeded:{p.passengers}>{rem}")

            # 產生預約編號：以「今日日期」為準
            today_iso = _today_iso_taipei()
            last_seq = _get_max_seq_for_date(ws_main, today_iso)
            booking_id = f"{_mmdd_prefix(today_iso)}{last_seq + 1:03d}"

            car_display = _display_trip_str(p.date, _time_hm_from_any(p.time))
            pk_idx, dp_idx, seg_str = _compute_indices_and_segments(p.pickLocation, p.dropLocation)
            em6 = _email_hash6(p.email)
            qr_content = f"FT:{booking_id}:{em6}"
            qr_url = f"{BASE_URL}/api/qr/{urllib.parse.quote(qr_content)}"

            newrow = [""] * len(headers)
            setv(newrow, "申請日期", _tz_now_str())
            setv(newrow, "預約狀態", BOOKED_TEXT)
            identity_simple = "住宿" if p.identity == "hotel" else "用餐"

            setv(newrow, "預約編號", booking_id)
            setv(newrow, "往返", p.direction)
            setv(newrow, "日期", p.date)
            setv(newrow, "班次", _time_hm_from_any(p.time))
            setv(newrow, "車次", car_display)
            setv(newrow, "上車地點", p.pickLocation)
            setv(newrow, "下車地點", p.dropLocation)
            setv(newrow, "姓名", p.name)
            setv(newrow, "手機", p.phone)
            setv(newrow, "信箱", p.email)
            setv(newrow, "預約人數", p.passengers)
            setv(newrow, "乘車狀態", "")
            setv(newrow, "身分", identity_simple)
            setv(newrow, "房號", p.roomNumber or "")
            setv(newrow, "入住日期", p.checkIn or "")
            setv(newrow, "退房日期", p.checkOut or "")
            setv(newrow, "用餐日期", p.diningDate or "")
            setv(newrow, "上車索引", pk_idx)
            setv(newrow, "下車索引", dp_idx)
            setv(newrow, "涉及路段範圍", seg_str)
            setv(newrow, "QRCode編碼", qr_content)
            setv(newrow, "寄信狀態", "")  # 先空白，稍後更新

            # 一次性寫入整列
            ws_main.append_row(newrow, value_input_option="USER_ENTERED")
            log.info(f"book appended booking_id={booking_id}")

            # 取得該列 rowno 以便更新寄信狀態
            all_values = _read_all_rows(ws_main)
            rownos = _find_rows_by_pred(ws_main, headers, HEADER_ROW_MAIN,
                                        lambda r: r.get("預約編號") == booking_id)
            rowno = rownos[0] if rownos else None

            # 寄信（失敗不阻擋）
            try:
                info = {
                    "booking_id": booking_id,
                    "date": p.date,
                    "time": _time_hm_from_any(p.time),
                    "direction": p.direction,
                    "pick": p.pickLocation,
                    "drop": p.dropLocation,
                    "name": p.name,
                    "phone": p.phone,
                    "email": p.email,
                    "pax": str(p.passengers),
                }
                subject, html = _compose_mail_html(info, "zh", "book")  # 語言以 zh 為預設，前端可傳 lang 改
                try:
                    _send_email_gmail(p.email, subject, html)
                    mail_note = f"{_tz_now_str()} 寄信成功"
                except Exception as e:
                    mail_note = f"{_tz_now_str()} 寄信失敗: {str(e)}"
                if rowno and "寄信狀態" in hmap:
                    ws_main.update_acell(gspread.utils.rowcol_to_a1(rowno, hmap["寄信狀態"]), mail_note)
                log.info(f"mail result: {mail_note}")
            except Exception as e:
                log.exception(f"mail block error but ignored: {e}")

            return {"status": "success", "booking_id": booking_id, "qr_url": qr_url, "qr_content": qr_content}

        # ===== 查詢 =====
        elif action == "query":
            p = QueryPayload(**data)
            if not (p.booking_id or p.phone or p.email):
                raise HTTPException(400, "至少提供 booking_id / phone / email 其中一項")

            all_values = _read_all_rows(ws_main)
            if not all_values:
                return []

            def get(row: List[str], key: str) -> str:
                return row[hmap[key] - 1] if key in hmap and len(row) >= hmap[key] else ""

            now, one_month_ago = datetime.now(), datetime.now() - timedelta(days=31)
            results: List[Dict[str, str]] = []
            for row in all_values[HEADER_ROW_MAIN:]:
                date_iso = get(row, "日期")
                try:
                    d = datetime.strptime(date_iso, "%Y-%m-%d")
                except:
                    d = now
                if d < one_month_ago:
                    continue
                if p.booking_id and p.booking_id != get(row, "預約編號"):
                    continue
                if p.phone and p.phone != get(row, "手機"):
                    continue
                if p.email and p.email != get(row, "信箱"):
                    continue
                rec = {k: get(row, k) for k in hmap}
                if rec.get("櫃台審核", "").lower() == "n":
                    rec["預約狀態"] = "已拒絕"
                results.append(rec)
            log.info(f"query results count={len(results)}")
            return results

        # ===== 修改 =====
        elif action == "modify":
            p = ModifyPayload(**data)
            # 找到目標列
            rownos = _find_rows_by_pred(ws_main, headers, HEADER_ROW_MAIN, lambda r: r.get("預約編號") == p.booking_id)
            if not rownos:
                raise HTTPException(404, "找不到此預約編號")
            rowno = rownos[0]

            # 讀舊值
            old_dir  = get_by_rowno(rowno, "往返")
            old_date = get_by_rowno(rowno, "日期")
            old_time = get_by_rowno(rowno, "班次") or get_by_rowno(rowno, "車次")
            old_pick = get_by_rowno(rowno, "上車地點")
            old_drop = get_by_rowno(rowno, "下車地點")
            try:
                old_pax = int(get_by_rowno(rowno, "預約人數") or "1")
            except:
                old_pax = 1

            new_dir  = p.direction or old_dir
            new_date = p.date or old_date
            new_time = _time_hm_from_any(p.time or old_time)
            new_pick = p.pickLocation or old_pick
            new_drop = p.dropLocation or old_drop
            new_pax  = int(p.passengers if p.passengers is not None else old_pax)

            # 容量檢查
            station_for_cap = _normalize_station_for_capacity(new_dir, new_pick, new_drop)
            rem = lookup_capacity(new_dir, new_date, new_time, station_for_cap)
            # 若仍在同一班次，僅需檢查「增加的差額」
            if (new_dir, new_date, new_time, _normalize_station_for_capacity(old_dir, old_pick, old_drop)) == (old_dir, old_date, _time_hm_from_any(old_time), _normalize_station_for_capacity(old_dir, old_pick, old_drop)):
                delta = new_pax - old_pax
                if delta > 0 and delta > rem:
                    raise HTTPException(409, f"capacity_exceeded_delta:{delta}>{rem}")
            else:
                if new_pax > rem:
                    raise HTTPException(409, f"capacity_exceeded:{new_pax}>{rem}")

            # 進行更新（批次）
            updates: Dict[str, str] = {}
            time_hm = new_time
            car_display = _display_trip_str(new_date, time_hm) if (new_date and time_hm) else None
            pk_idx = dp_idx = None
            seg_str = None
            if p.pickLocation and p.dropLocation:
                pk_idx, dp_idx, seg_str = _compute_indices_and_segments(new_pick, new_drop)

            updates["預約狀態"] = BOOKED_TEXT
            updates["預約人數"] = str(new_pax)
            if "備註" in hmap:
                current_note = ws_main.cell(rowno, hmap["備註"]).value or ""
                new_note = f"{_tz_now_str()} 已修改"
                updates["備註"] = f"{current_note}; {new_note}" if current_note else new_note

            updates["往返"] = new_dir
            updates["日期"] = new_date
            if time_hm: updates["班次"] = time_hm
            if car_display: updates["車次"] = car_display
            updates["上車地點"] = new_pick
            updates["下車地點"] = new_drop
            if p.phone: updates["手機"] = p.phone
            if p.email:
                updates["信箱"] = p.email
                em6 = _email_hash6(p.email)
                qr_content = f"FT:{p.booking_id}:{em6}"
                updates["QRCode編碼"] = qr_content
            if pk_idx is not None: updates["上車索引"] = str(pk_idx)
            if dp_idx is not None: updates["下車索引"] = str(dp_idx)
            if seg_str is not None: updates["涉及路段範圍"] = seg_str
            if "最後操作時間" in hmap:
                updates["最後操作時間"] = _tz_now_str() + " 已修改"

            batch_updates = []
            for col_name, value in updates.items():
                if col_name in hmap:
                    batch_updates.append({
                        'range': gspread.utils.rowcol_to_a1(rowno, hmap[col_name]),
                        'values': [[value]]
                    })
            if batch_updates:
                ws_main.batch_update(batch_updates)
            log.info(f"modify updated booking_id={p.booking_id}")

            # 寄信（失敗不阻擋）
            try:
                info = {
                    "booking_id": p.booking_id,
                    "date": new_date,
                    "time": new_time,
                    "direction": new_dir,
                    "pick": new_pick,
                    "drop": new_drop,
                    "name": get_by_rowno(rowno, "姓名"),
                    "phone": get_by_rowno(rowno, "手機"),
                    "email": get_by_rowno(rowno, "信箱"),
                    "pax": str(new_pax),
                }
                subject, html = _compose_mail_html(info, "zh", "modify")
                try:
                    _send_email_gmail(info["email"], subject, html)
                    mail_note = f"{_tz_now_str()} 寄信成功"
                except Exception as e:
                    mail_note = f"{_tz_now_str()} 寄信失敗: {str(e)}"
                if "寄信狀態" in hmap:
                    ws_main.update_acell(gspread.utils.rowcol_to_a1(rowno, hmap["寄信狀態"]), mail_note)
                log.info(f"mail result: {mail_note}")
            except Exception as e:
                log.exception(f"mail block error but ignored: {e}")

            return {"status": "success", "booking_id": p.booking_id}

        # ===== 刪除（取消） =====
        elif action == "delete":
            p = DeletePayload(**data)
            rownos = _find_rows_by_pred(ws_main, headers, HEADER_ROW_MAIN, lambda r: r.get("預約編號") == p.booking_id)
            if not rownos:
                raise HTTPException(404, "找不到此預約編號")
            rowno = rownos[0]

            updates: Dict[str, str] = {}
            if "預約狀態" in hmap:
                updates["預約狀態"] = CANCELLED_TEXT
            if "備註" in hmap:
                current_note = ws_main.cell(rowno, hmap["備註"]).value or ""
                new_note = f"{_tz_now_str()} 已取消"
                updates["備註"] = f"{current_note}; {new_note}" if current_note else new_note
            if "最後操作時間" in hmap:
                updates["最後操作時間"] = _tz_now_str() + " 已刪除"

            batch_updates = []
            for col_name, value in updates.items():
                if col_name in hmap:
                    batch_updates.append({
                        'range': gspread.utils.rowcol_to_a1(rowno, hmap[col_name]),
                        'values': [[value]]
                    })
            if batch_updates:
                ws_main.batch_update(batch_updates)
            log.info(f"delete updated booking_id={p.booking_id}")

            # 寄信（失敗不阻擋）
            try:
                info = {
                    "booking_id": p.booking_id,
                    "date": get_by_rowno(rowno, "日期"),
                    "time": _time_hm_from_any(get_by_rowno(rowno, "班次") or get_by_rowno(rowno, "車次")),
                    "direction": get_by_rowno(rowno, "往返"),
                    "pick": get_by_rowno(rowno, "上車地點"),
                    "drop": get_by_rowno(rowno, "下車地點"),
                    "name": get_by_rowno(rowno, "姓名"),
                    "phone": get_by_rowno(rowno, "手機"),
                    "email": get_by_rowno(rowno, "信箱"),
                    "pax": get_by_rowno(rowno, "預約人數") or "1",
                }
                subject, html = _compose_mail_html(info, "zh", "cancel")
                try:
                    _send_email_gmail(info["email"], subject, html)
                    mail_note = f"{_tz_now_str()} 寄信成功"
                except Exception as e:
                    mail_note = f"{_tz_now_str()} 寄信失敗: {str(e)}"
                if "寄信狀態" in hmap:
                    ws_main.update_acell(gspread.utils.rowcol_to_a1(rowno, hmap["寄信狀態"]), mail_note)
                log.info(f"mail result: {mail_note}")
            except Exception as e:
                log.exception(f"mail block error but ignored: {e}")

            return {"status": "success", "booking_id": p.booking_id}

        # ===== 掃碼上車 =====
        elif action == "check_in":
            p = CheckInPayload(**data)
            if not (p.code or p.booking_id):
                raise HTTPException(400, "需提供 code 或 booking_id")

            rownos = _find_rows_by_pred(
                ws_main, headers, HEADER_ROW_MAIN,
                lambda r: r.get("QRCode編碼") == p.code or r.get("預約編號") == p.booking_id,
            )
            if not rownos:
                raise HTTPException(404, "找不到符合條件之訂單")
            rowno = rownos[0]

            updates: Dict[str, str] = {}
            if "乘車狀態" in hmap:
                updates["乘車狀態"] = "已上車"
            if "最後操作時間" in hmap:
                updates["最後操作時間"] = _tz_now_str() + " 已上車"

            batch_updates = []
            for col_name, value in updates.items():
                if col_name in hmap:
                    batch_updates.append({
                        'range': gspread.utils.rowcol_to_a1(rowno, hmap[col_name]),
                        'values': [[value]]
                    })
            if batch_updates:
                ws_main.batch_update(batch_updates)
            log.info(f"check_in row={rowno}")

            return {"status": "success", "row": rowno}

        # ===== 寄信（手動補寄） =====
        elif action == "mail":
            p = MailPayload(**data)
            rownos = _find_rows_by_pred(ws_main, headers, HEADER_ROW_MAIN, lambda r: r.get("預約編號") == p.booking_id)
            if not rownos:
                raise HTTPException(404, "找不到此預約編號")
            rowno = rownos[0]

            get = lambda k: get_by_rowno(rowno, k)
            info = {
                "booking_id": get("預約編號"),
                "date": get("日期"),
                "time": _time_hm_from_any(get("班次") or get("車次")),
                "direction": get("往返"),
                "pick": get("上車地點"),
                "drop": get("下車地點"),
                "name": get("姓名"),
                "phone": get("手機"),
                "email": get("信箱"),
                "pax": get("預約人數") or "1",
            }

            subject, html = _compose_mail_html(info, p.lang, p.kind)

            attachment_bytes: Optional[bytes] = None
            if p.kind in ("book", "modify") and p.ticket_png_base64:
                b64 = p.ticket_png_base64
                if "," in b64:
                    b64 = b64.split(",", 1)[1]
                try:
                    attachment_bytes = base64.b64decode(b64, validate=True)
                except Exception:
                    attachment_bytes = None

            try:
                _send_email_gmail(info["email"], subject, html, attachment=attachment_bytes, attachment_filename=f"ticket_{info['booking_id']}.png" if attachment_bytes else "ticket.png")
                status_text = f"{_tz_now_str()} 寄信成功"
            except Exception as e:
                status_text = f"{_tz_now_str()} 寄信失敗: {str(e)}"

            if "寄信狀態" in hmap:
                ws_main.update_acell(gspread.utils.rowcol_to_a1(rowno, hmap["寄信狀態"]), status_text)

            log.info(f"manual mail result: {status_text}")
            return {"status": "success" if "成功" in status_text else "mail_failed", "booking_id": p.booking_id, "mail_note": status_text}

        else:
            raise HTTPException(400, f"未知 action：{action}")

    except HTTPException:
        raise
    except Exception as e:
        log.exception("server error")
        raise HTTPException(500, f"伺服器錯誤: {str(e)}")

@app.get("/api/qr/{code}")
def qr_image(code: str):
    try:
        decoded_code = urllib.parse.unquote(code)
        img = qrcode.make(decoded_code)
        bio = io.BytesIO()
        img.save(bio, format="PNG")
        return Response(content=bio.getvalue(), media_type="image/png")
    except Exception as e:
        raise HTTPException(500, f"QR 生成失敗: {str(e)}")

@app.get("/cors_debug")
def cors_debug():
    return {"status": "ok", "cors_test": True, "time": _tz_now_str()}

@app.get("/api/debug")
def debug_endpoint():
    return {"status": "服務正常", "base_url": BASE_URL, "time": _tz_now_str()}
