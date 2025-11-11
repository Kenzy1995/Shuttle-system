from __future__ import annotations
import io
import os
import time
import base64
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional
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

# ========== 常數與工具 ==========
SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
    "https://www.googleapis.com/auth/gmail.send",  # 新增：寄信
]
SPREADSHEET_ID = "1xp54tKOczklmT8uacW-HMxwV8r0VOR2ui33jYcE2pUQ"
SHEET_NAME = "預約審核(櫃台)"
BASE_URL = "https://booking-manager-995728097341.asia-east1.run.app"

EMAIL_FROM_NAME = "汐止福泰大飯店櫃檯"
EMAIL_FROM_ADDR = "fortehotels.shuttle@gmail.com"

# 表頭列（1-based）
HEADER_ROW = 2

# 狀態固定字串
BOOKED_TEXT = "✔️ 已預約 Booked"
CANCELLED_TEXT = "❌ 已取消 Cancelled"

# 僅允許精準欄位名稱（不做別名）
HEADER_KEYS = {
    "申請日期",
    "最後操作時間",
    "預約編號",
    "往返",
    "日期",
    "班次",
    "車次",
    "上車地點",
    "下車地點",
    "姓名",
    "手機",
    "信箱",
    "預約人數",
    "櫃台審核",
    "預約狀態",
    "乘車狀態",
    "身分",
    "房號",
    "入住日期",
    "退房日期",
    "用餐日期",
    "上車索引",
    "下車索引",
    "涉及路段範圍",
    "QRCode編碼",
    "備註",
    # 新增：寄信欄位（使用「絕對文字表頭名稱」）
    "已寄信",
    "寄信狀態",
}

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

def _time_hm_from_any(s: str) -> str:
    s = (s or "").strip().replace("：", ":")
    if " " in s and ":" in s:
        return s.split()[-1][:5]
    if ":" in s:
        hhmm = s[:5]
        # 可能是 mm/dd HH:MM 這種，前兩碼非數字時仍保留 HH:MM
        return hhmm
    return s

def _display_trip_str(date_iso: str, time_hm: str) -> str:
    # 供 sheet 顯示的「車次」：純文字 mm/dd HH:MM
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

# ========== Google Sheets ==========
def open_sheet() -> gspread.Worksheet:
    try:
        credentials, _ = google.auth.default(scopes=SCOPES)
        gc = gspread.authorize(credentials)
        sh = gc.open_by_key(SPREADSHEET_ID)
        ws = sh.worksheet(SHEET_NAME)
        return ws
    except Exception as e:
        raise RuntimeError(f"無法開啟 Google Sheet: {str(e)}")

def _sheet_headers(ws: gspread.Worksheet) -> List[str]:
    headers = ws.row_values(HEADER_ROW)
    return [h.strip() for h in headers]

def header_map(ws: gspread.Worksheet) -> Dict[str, int]:
    row = _sheet_headers(ws)
    m: Dict[str, int] = {}
    for idx, name in enumerate(row, start=1):
        name = (name or "").strip()
        if name in HEADER_KEYS and name not in m:
            m[name] = idx
    return m

def _read_all_rows(ws: gspread.Worksheet) -> List[List[str]]:
    return ws.get_all_values()

def _find_rows_by_pred(ws: gspread.Worksheet, pred) -> List[int]:
    values = _read_all_rows(ws)
    if not values:
        return []
    headers = values[HEADER_ROW - 1] if len(values) >= HEADER_ROW else []
    result = []
    for i, row in enumerate(values[HEADER_ROW:], start=HEADER_ROW + 1):
        if not any(row):
            continue
        d = {headers[j]: row[j] if j < len(row) else "" for j in range(len(headers))}
        if pred(d):
            result.append(i)
    return result

def _get_max_seq_for_date(ws: gspread.Worksheet, date_iso: str) -> int:
    m = header_map(ws)
    all_values = _read_all_rows(ws)
    if not all_values or "預約編號" not in m:
        return 0
    c_id = m["預約編號"]
    prefix = _mmdd_prefix(date_iso)
    max_seq = 0
    for row in all_values[HEADER_ROW:]:
        booking = row[c_id - 1] if c_id - 1 < len(row) else ""
        if booking.startswith(prefix):
            try:
                seq = int(booking[len(prefix):])
                max_seq = max(max_seq, seq)
            except:
                pass
    return max_seq

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
    lang: str = Field("zh", regex="^(zh|en|ja|ko)$")
    kind: str = Field(..., regex="^(book|modify|cancel)$")
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

def _compose_mail_html(info: Dict[str, str], lang: str, kind: str) -> (str, str):
    # 主旨
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

    # 共同內容
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
app = FastAPI(title="Shuttle Ops API", version="1.2.0")

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

# ========== 主 API ==========
@app.post("/api/ops")
def ops(req: OpsRequest):
    action = (req.action or "").strip().lower()
    data = req.data or {}

    try:
        ws = open_sheet()
        hmap = header_map(ws)
        headers = _sheet_headers(ws)

        def setv(row_arr: List[str], col: str, v: Any):
            if col in hmap and 1 <= hmap[col] <= len(row_arr):
                row_arr[hmap[col] - 1] = v if isinstance(v, str) else str(v)

        def get_by_rowno(rowno: int, key: str) -> str:
            if key not in hmap:
                return ""
            return ws.cell(rowno, hmap[key]).value or ""

        # ===== 新增預約 =====
        if action == "book":
            p = BookPayload(**data)

            # 產生預約編號
            last_seq = _get_max_seq_for_date(ws, p.date)
            booking_id = f"{_mmdd_prefix(p.date)}{last_seq + 1:03d}"
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
            setv(newrow, "班次", _time_hm_from_any(p.time))  # 僅 HH:MM
            setv(newrow, "車次", car_display)                # mm/dd HH:MM 純文字
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

            ws.append_row(newrow, value_input_option="USER_ENTERED")
            return {"status": "success", "booking_id": booking_id, "qr_url": qr_url, "qr_content": qr_content}

        # ===== 查詢 =====
        elif action == "query":
            p = QueryPayload(**data)
            if not (p.booking_id or p.phone or p.email):
                raise HTTPException(400, "至少提供 booking_id / phone / email 其中一項")

            all_values = _read_all_rows(ws)
            if not all_values:
                return []

            def get(row: List[str], key: str) -> str:
                return row[hmap[key] - 1] if key in hmap and len(row) >= hmap[key] else ""

            now, one_month_ago = datetime.now(), datetime.now() - timedelta(days=31)
            results: List[Dict[str, str]] = []
            for row in all_values[HEADER_ROW:]:
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

            return results

        # ===== 修改 =====
        elif action == "modify":
            p = ModifyPayload(**data)
            target = _find_rows_by_pred(ws, lambda r: r.get("預約編號") == p.booking_id)
            if not target:
                raise HTTPException(404, "找不到此預約編號")
            rowno = target[0]

            # 班次與路段
            time_hm = _time_hm_from_any(p.time or "")
            car_display = _display_trip_str(p.date or "", time_hm) if (p.date and time_hm) else None

            pk_idx = dp_idx = None
            seg_str = None
            if p.pickLocation and p.dropLocation:
                pk_idx, dp_idx, seg_str = _compute_indices_and_segments(p.pickLocation, p.dropLocation)

            def upd(col: str, v: Optional[str]):
                if v is None:
                    return
                if col in hmap:
                    ws.update_cell(rowno, hmap[col], v)

            # 覆蓋狀態與人數（確保寫入「預約人數」欄位 Q）
            upd("預約狀態", BOOKED_TEXT)
            if p.passengers is not None:
                upd("預約人數", str(p.passengers))  # 僅寫入「預約人數」，不碰「確認人數」

            # 備註
            if "備註" in hmap:
                current_note = ws.cell(rowno, hmap["備註"]).value or ""
                new_note = f"{_tz_now_str()} 已修改"
                if current_note:
                    new_note = f"{current_note}; {new_note}"
                upd("備註", new_note)

            if p.direction: upd("往返", p.direction)
            if p.date: upd("日期", p.date)
            if time_hm: upd("班次", time_hm)
            if car_display: upd("車次", car_display)
            if p.pickLocation: upd("上車地點", p.pickLocation)
            if p.dropLocation: upd("下車地點", p.dropLocation)
            if p.phone: upd("手機", p.phone)
            if p.email:
                upd("信箱", p.email)
                # 依新 email 重算 QR
                em6 = _email_hash6(p.email)
                qr_content = f"FT:{p.booking_id}:{em6}"
                upd("QRCode編碼", qr_content)
            if pk_idx is not None: upd("上車索引", str(pk_idx))
            if dp_idx is not None: upd("下車索引", str(dp_idx))
            if seg_str is not None: upd("涉及路段範圍", seg_str)
            if "最後操作時間" in hmap:
                ws.update_cell(rowno, hmap["最後操作時間"], _tz_now_str() + " 已修改")

            return {"status": "success", "booking_id": p.booking_id}

        # ===== 刪除（取消）=====
        elif action == "delete":
            p = DeletePayload(**data)
            target = _find_rows_by_pred(ws, lambda r: r.get("預約編號") == p.booking_id)
            if not target:
                raise HTTPException(404, "找不到此預約編號")
            rowno = target[0]
            if "預約狀態" in hmap:
                ws.update_cell(rowno, hmap["預約狀態"], CANCELLED_TEXT)
            if "備註" in hmap:
                current_note = ws.cell(rowno, hmap["備註"]).value or ""
                new_note = f"{_tz_now_str()} 已取消"
                if current_note:
                    new_note = f"{current_note}; {new_note}"
                ws.update_cell(rowno, hmap["備註"], new_note)
            if "最後操作時間" in hmap:
                ws.update_cell(rowno, hmap["最後操作時間"], _tz_now_str() + " 已刪除")
            return {"status": "success", "booking_id": p.booking_id}

        # ===== 掃碼上車 =====
        elif action == "check_in":
            p = CheckInPayload(**data)
            if not (p.code or p.booking_id):
                raise HTTPException(400, "需提供 code 或 booking_id")
            target = _find_rows_by_pred(
                ws,
                lambda r: r.get("QRCode編碼") == p.code or r.get("預約編號") == p.booking_id,
            )
            if not target:
                raise HTTPException(404, "找不到符合條件之訂單")
            rowno = target[0]
            if "乘車狀態" in hmap:
                ws.update_cell(rowno, hmap["乘車狀態"], "已上車")
            if "最後操作時間" in hmap:
                ws.update_cell(rowno, hmap["最後操作時間"], _tz_now_str() + " 已上車")
            return {"status": "success", "row": rowno}

        # ===== 寄信（成功預約／變更／取消） =====
        elif action == "mail":
            p = MailPayload(**data)
            target = _find_rows_by_pred(ws, lambda r: r.get("預約編號") == p.booking_id)
            if not target:
                raise HTTPException(404, "找不到此預約編號")
            rowno = target[0]

            # 讀取行資料
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

            # 處理圖片附件（book/modify 才需要）
            attachment_bytes: Optional[bytes] = None
            if p.kind in ("book", "modify") and p.ticket_png_base64:
                b64 = p.ticket_png_base64
                if "," in b64:  # data:image/png;base64,xxxx
                    b64 = b64.split(",", 1)[1]
                try:
                    attachment_bytes = base64.b64decode(b64, validate=True)
                except Exception:
                    attachment_bytes = None

            # 寄信
            try:
                _send_email_gmail(info["email"], subject, html, attachment=attachment_bytes, attachment_filename=f"ticket_{info['booking_id']}.png" if attachment_bytes else "ticket.png")
                # 更新 sheet 標記
                if "已寄信" in hmap:
                    ws.update_cell(rowno, hmap["已寄信"], "已寄信")
                if "寄信狀態" in hmap:
                    ws.update_cell(rowno, hmap["寄信狀態"], f"{_tz_now_str()} 已寄信")
            except Exception as e:
                raise HTTPException(500, f"寄信失敗：{str(e)}")

            return {"status": "success", "booking_id": p.booking_id}

        else:
            raise HTTPException(400, f"未知 action：{action}")

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"伺服器錯誤: {str(e)}")

@app.get("/cors_debug")
def cors_debug():
    return {"status": "ok", "cors_test": True, "time": _tz_now_str()}

@app.get("/api/debug")
def debug_endpoint():
    return {"status": "服務正常", "base_url": BASE_URL, "time": _tz_now_str()}
