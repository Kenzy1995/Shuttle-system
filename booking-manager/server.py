# -*- coding: utf-8 -*-
import base64
import io
import os
import time
import json
import qrcode
from typing import Any, Dict, List, Optional, Tuple

import gspread
from google.auth import default as google_auth_default
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel

import requests
from email.message import EmailMessage
import smtplib

# -----------------------------
# Config
# -----------------------------
SPREADSHEET_ID = os.getenv("SPREADSHEET_ID", "")
SHEET_NAME = os.getenv("SHEET_NAME", "預約整理(自動)")
SCHEDULE_API_URL = os.getenv("SCHEDULE_API_URL", "https://booking-api-995728097341.asia-east1.run.app/api/sheet")

SMTP_HOST = os.getenv("SMTP_HOST", "")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASS = os.getenv("SMTP_PASS", "")
SMTP_FROM = os.getenv("SMTP_FROM", "fortehotels.shuttle@gmail.com")
SENDER_NAME = os.getenv("SENDER_NAME", "汐止福泰大飯店櫃檯")

# -----------------------------
# App
# -----------------------------
app = FastAPI(title="Booking OPS")

# -----------------------------
# Helpers
# -----------------------------

def get_sheet_and_header() -> Tuple[gspread.Worksheet, Dict[str, int]]:
    # Open the Google Sheet and return worksheet and header name->index mapping (1-based).
    creds, _ = google_auth_default(scopes=[
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ])
    client = gspread.authorize(creds)
    sh = client.open_by_key(SPREADSHEET_ID)
    ws = sh.worksheet(SHEET_NAME)
    header = ws.row_values(1)
    name_to_idx = {name.strip(): i+1 for i, name in enumerate(header)}
    return ws, name_to_idx

def ensure_mail_sent_column(ws: gspread.Worksheet, name_to_idx: Dict[str, int]) -> Dict[str, int]:
    # Ensure a column '已寄信' exists (Y 欄). If not, append at the end of header.
    if "已寄信" not in name_to_idx:
        header = ws.row_values(1)
        header.append("已寄信")
        ws.update('A1', [header])
        name_to_idx = {name.strip(): i+1 for i, name in enumerate(header)}
    return name_to_idx

def find_row_by_booking_id(ws: gspread.Worksheet, name_to_idx: Dict[str, int], booking_id: str) -> Optional[int]:
    # Find row number (1-based) by booking_id. Return None if not found.
    if "預約編號" not in name_to_idx:
        return None
    col = name_to_idx["預約編號"]
    col_values = ws.col_values(col)
    for i, v in enumerate(col_values[1:], start=2):  # skip header
        if str(v).strip() == str(booking_id).strip():
            return i
    return None

def parse_time_only(s: str) -> str:
    # Extract 'HH:MM' from strings like '11/11 21:00' or '21:00' or ISO.
    if not s:
        return ""
    s = s.replace("：", ":").strip()
    if " " in s and "/" in s:
        try:
            return s.split()[-1][:5]
        except Exception:
            pass
    if "T" in s and len(s) >= 16:
        return s[11:16]
    if ":" in s:
        parts = s.split(":")
        if parts and len(parts[0]) <= 2:
            mm = parts[1][:2] if len(parts) > 1 else "00"
            hh = parts[0].zfill(2)
            return f"{hh}:{mm}"
    return s[-5:]

def now_ts_ms() -> int:
    return int(time.time() * 1000)

def gen_booking_id() -> str:
    # Simple unique id: YYMMDD + last 6 digits of ms timestamp
    t = time.localtime()
    prefix = time.strftime("%y%m%d", t)
    suffix = str(now_ts_ms())[-6:]
    return f"{prefix}{suffix}"

def build_qr_png_bytes(content: str) -> bytes:
    img = qrcode.make(content or "")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()

def smtp_send_mail(to_email: str, subject: str, html_body: str, png_attachment: Optional[bytes], filename: str = "ticket.png") -> None:
    if not (SMTP_HOST and SMTP_USER and SMTP_PASS):
        # No SMTP configured; silently skip (but do not fail booking flow)
        return
    msg = EmailMessage()
    msg["From"] = f"{SENDER_NAME} <{SMTP_FROM}>"
    msg["To"] = to_email
    msg["Subject"] = subject
    msg.set_content("HTML only")
    msg.add_alternative(html_body, subtype="html")
    if png_attachment:
        msg.add_attachment(png_attachment, maintype="image", subtype="png", filename=filename)
    with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
        server.starttls()
        server.login(SMTP_USER, SMTP_PASS)
        server.send_message(msg)

def mark_mail_sent(ws: gspread.Worksheet, name_to_idx: Dict[str, int], row_idx: int) -> None:
    name_to_idx = ensure_mail_sent_column(ws, name_to_idx)
    col = name_to_idx["已寄信"]
    ws.update_cell(row_idx, col, "已寄信")

def capacity_check(direction: str, date_iso: str, station: str, time_hhmm: str, own_pax: int = 0) -> int:
    # Return available seats possibly including own_pax if same booking is retained.
    try:
        r = requests.get(SCHEDULE_API_URL, timeout=10)
        r.raise_for_status()
        data = r.json()
        headers = data[0]
        rows = data[1:]
        def idx(name: str) -> int:
            try:
                return headers.index(name)
            except ValueError:
                return -1
        i_dir = idx("去程 / 回程")
        i_date = idx("日期")
        i_site = idx("站點")
        i_sched = idx("班次")
        i_av = idx("可預約人數") if "可預約人數" in headers else idx("可約人數 / Available")
        avail = 0
        for r0 in rows:
            try:
                if str(r0[i_dir]).strip() != direction.strip():
                    continue
                # unify date
                ds = str(r0[i_date]).strip()
                if "/" in ds and len(ds.split("/")[0])==4:
                    y,m,d = ds.split("/")
                    ds = f"{y}-{int(m):02d}-{int(d):02d}"
                if ds != date_iso:
                    continue
                if str(r0[i_site]).strip() != station.strip():
                    continue
                time_only = parse_time_only(str(r0[i_sched]))
                if time_only != time_hhmm:
                    continue
                avs = str(r0[i_av]).strip() if i_av >= 0 else "0"
                digits = "".join([ch for ch in avs if ch.isdigit()])
                avail = int(digits or "0")
                break
            except Exception:
                continue
        return max(0, avail + max(0, own_pax))
    except Exception:
        return 0

# -----------------------------
# Models
# -----------------------------
class OpsEnvelope(BaseModel):
    action: str
    data: Dict[str, Any]

# -----------------------------
# Routes
# -----------------------------

@app.get("/api/qr/{code}")
def qr_code(code: str):
    # Return QR code PNG for 'code' string.
    png = build_qr_png_bytes(code)
    return StreamingResponse(io.BytesIO(png), media_type="image/png")

@app.post("/api/ops")
def ops(envelope: OpsEnvelope, request: Request):
    action = envelope.action
    d = envelope.data or {}
    try:
        if action == "book":
            return handle_book(d, request)
        if action == "modify":
            return handle_modify(d, request)
        if action == "delete":
            return handle_delete(d, request)
        if action == "query":
            return handle_query(d)
        if action == "email":
            return handle_email(d)
        raise HTTPException(status_code=400, detail="Unknown action")
    except HTTPException as he:
        raise he
    except Exception as e:
        return JSONResponse({"status":"error","detail":str(e)}, status_code=500)

# -----------------------------
# Handlers
# -----------------------------

def handle_book(d: Dict[str, Any], request: Request):
    required = ["direction","date","station","time","name","phone","email","passengers","pickLocation","dropLocation"]
    for k in required:
        if k not in d or d[k] in (None,""):
            raise HTTPException(status_code=400, detail=f"Missing field: {k}")

    direction = d["direction"]
    date_iso = d["date"]
    station = d["station"]
    time_hhmm = parse_time_only(str(d["time"]))
    passengers = int(d["passengers"])

    avail = capacity_check(direction, date_iso, station, time_hhmm, own_pax=0)
    if passengers > min(4, avail):
        return JSONResponse({"status":"error","detail":"exceeds capacity"}, status_code=400)

    ws, name_to_idx = get_sheet_and_header()
    booking_id = gen_booking_id()
    qr_content = booking_id  # encode id

    # Create row map based on headers (write only known headers)
    row_map = {
        "預約編號": booking_id,
        "申請日期": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime()),
        "預約狀態": "已預約",
        "乘車狀態": "",
        "姓名": d.get("name",""),
        "手機": d.get("phone",""),
        "信箱": d.get("email",""),
        "身分": d.get("identity",""),
        "房號": d.get("roomNumber",""),
        "入住日期": d.get("checkIn",""),
        "退房日期": d.get("checkOut",""),
        "用餐日期": d.get("diningDate",""),
        "往返": direction,
        "上車地點": d.get("pickLocation",""),
        "下車地點": d.get("dropLocation",""),
        "車次": f"{time_hhmm}",
        "預約人數": passengers,
        "QRCode編碼": qr_content,
    }

    # Build row in header order
    header = ws.row_values(1)
    new_row = [row_map.get(h,"") for h in header]
    ws.append_row(new_row, value_input_option="USER_ENTERED")

    # Build qr url
    base_url = str(request.base_url).rstrip("/")
    qr_url = f"{base_url}/api/qr/{qr_content}"

    return {"status":"success","booking_id": booking_id, "qr_url": qr_url}

def handle_modify(d: Dict[str, Any], request: Request):
    required = ["booking_id","direction","date","time","passengers","pickLocation","dropLocation","phone","email","station"]
    for k in required:
        if k not in d or d[k] in (None,""):
            raise HTTPException(status_code=400, detail=f"Missing field: {k}")

    booking_id = str(d["booking_id"]).strip()
    direction = d["direction"]
    date_iso = d["date"]
    station = d["station"]
    time_hhmm = parse_time_only(str(d["time"]))
    new_pax = int(d["passengers"])

    ws, name_to_idx = get_sheet_and_header()
    row_idx = find_row_by_booking_id(ws, name_to_idx, booking_id)
    if not row_idx:
        raise HTTPException(status_code=404, detail="booking not found")

    # Read original values to compute "include self"
    row_values = ws.row_values(row_idx)
    hdr = ws.row_values(1)
    h2i = {name: i for i, name in enumerate(hdr)}
    old_dir = row_values[h2i.get("往返", -1)] if h2i.get("往返", -1) >= 0 else ""
    old_date = row_values[h2i.get("日期", -1)] if h2i.get("日期", -1) >= 0 else ""
    old_station = row_values[h2i.get("上車地點", -1)] if h2i.get("上車地點", -1) >= 0 else ""
    old_time = parse_time_only(row_values[h2i.get("車次", -1)]) if h2i.get("車次", -1) >= 0 else ""
    old_pax = int(row_values[h2i.get("預約人數", -1)] or "1") if h2i.get("預約人數", -1) >= 0 else 1

    same_as_original = (old_dir==direction) and (old_date==date_iso) and (old_station== (station if direction=="回程" else d.get("dropLocation",""))) and (old_time==time_hhmm)
    avail = capacity_check(direction, date_iso, station, time_hhmm, own_pax=(old_pax if same_as_original else 0))
    if new_pax > min(4, avail):
        return JSONResponse({"status":"error","detail":"exceeds capacity"}, status_code=400)

    # Update only relevant fields
    updates = {
        "往返": direction,
        "日期": date_iso,
        "上車地點": d.get("pickLocation",""),
        "下車地點": d.get("dropLocation",""),
        "車次": f"{time_hhmm}",
        "預約人數": new_pax,  # ★ 寫到「預約人數」Q欄
        "手機": d.get("phone",""),
        "信箱": d.get("email",""),
        "站點": station  # 若表內有此欄位
    }
    # Push updates by cell
    for k, v in updates.items():
        if k in name_to_idx:
            ws.update_cell(row_idx, name_to_idx[k], v)

    # Keep same QR
    qr_content = row_values[h2i.get("QRCode編碼",-1)] if h2i.get("QRCode編碼",-1) >= 0 else booking_id
    base_url = str(request.base_url).rstrip("/")
    qr_url = f"{base_url}/api/qr/{qr_content}"

    return {"status":"success","booking_id": booking_id, "qr_code": qr_content, "qr_url": qr_url}

def handle_delete(d: Dict[str, Any], request: Request):
    booking_id = str(d.get("booking_id","")).strip()
    if not booking_id:
        raise HTTPException(status_code=400, detail="Missing booking_id")
    ws, name_to_idx = get_sheet_and_header()
    row_idx = find_row_by_booking_id(ws, name_to_idx, booking_id)
    if not row_idx:
        raise HTTPException(status_code=404, detail="booking not found")
    # 標記取消
    if "預約狀態" in name_to_idx:
        ws.update_cell(row_idx, name_to_idx["預約狀態"], "已取消")
    if "乘車狀態" in name_to_idx:
        ws.update_cell(row_idx, name_to_idx["乘車狀態"], "")
    return {"status":"success","booking_id": booking_id}

def handle_query(d: Dict[str, Any]):
    booking_id = str(d.get("booking_id","")).strip()
    phone = str(d.get("phone","")).strip()
    email = str(d.get("email","")).strip()

    if not any([booking_id, phone, email]):
        raise HTTPException(status_code=400, detail="missing query fields")

    ws, name_to_idx = get_sheet_and_header()
    records = ws.get_all_records()  # list of dict by header
    results: List[Dict[str, Any]] = []
    for row in records:
        bid_ok = booking_id and str(row.get("預約編號","")).strip() == booking_id
        phone_ok = phone and str(row.get("手機","")).strip() == phone
        email_ok = email and str(row.get("信箱","")).strip().lower() == email.lower()
        if booking_id:
            ok = bid_ok
        elif phone and email:
            ok = phone_ok and email_ok
        elif phone:
            ok = phone_ok
        else:
            ok = email_ok
        if ok:
            results.append(row)
    return JSONResponse({"status":"success","results": results})

def multilingual_body(data: Dict[str, Any], typ: str) -> str:
    # typ: book / modify / cancel
    name = data.get("name","")
    booking_id = data.get("bookingId") or data.get("booking_id","")
    time_hhmm = parse_time_only(str(data.get("time","")))
    passengers = data.get("passengers","")
    direction = data.get("direction","")
    phone = data.get("phone","")
    guest_email = data.get("email","")
    pickup = data.get("pickLocation","")
    dropoff = data.get("dropLocation","")
    lang = (data.get("lang") or "en").lower()

    # Chinese body
    zh_lines = []
    if typ == "cancel":
        zh_lines.append(f"<p style='color:black;'>親愛的客戶，您的接駁車預約（編號：{booking_id}）已成功取消。</p>")
    else:
        zh_lines.append(f"<p style='color:black;'>尊敬的 {name} 貴賓，您好！</p>")
        zh_lines.append(f"<p style='color:black;'>以下為您的{ '修改後' if typ=='modify' else '預約' }詳情：</p>")
        zh_lines.append(f"<p style='color:black;'> - 預約編號：{booking_id}</p>")
        zh_lines.append(f"<p style='color:black;'> - 預約班次：{time_hhmm} (GMT+8)</p>")
        zh_lines.append(f"<p style='color:black;'> - 預約人數：{passengers}</p>")
        zh_lines.append(f"<p style='color:black;'> - 往返方向：{direction}</p>")
        zh_lines.append(f"<p style='color:black;'> - 上車站點：{pickup}</p>")
        zh_lines.append(f"<p style='color:black;'> - 下車站點：{dropoff}</p>")
        zh_lines.append(f"<p style='color:black;'> - 手機：{phone}</p>")
        zh_lines.append(f"<p style='color:black;'> - 信箱：{guest_email}</p>")

    zh_tail = "<p style='color:black;'>如有任何問題，請致電 (02-2691-9222 #1)。祝您旅途愉快！</p><p style='color:black;'>汐止福泰大飯店 敬上</p>"
    zh = "\n".join(zh_lines) + zh_tail

    # Second language
    if lang == "ja":
        en_lines = []
        if typ == "cancel":
            en_lines.append(f"<p style='color:black;'>ご予約（番号：{booking_id}）は正常にキャンセルされました。</p>")
        else:
            en_lines.append(f"<p style='color:black;'>以下は{ '変更後' if typ=='modify' else 'ご予約' }の詳細です。</p>")
            en_lines.append(f"<p style='color:black;'> - 予約番号: {booking_id}</p>")
            en_lines.append(f"<p style='color:black;'> - 便（時間）: {time_hhmm} (GMT+8)</p>")
            en_lines.append(f"<p style='color:black;'> - 人数: {passengers}</p>")
            en_lines.append(f"<p style='color:black;'> - 方向: {direction}</p>")
            en_lines.append(f"<p style='color:black;'> - 乗車：{pickup}</p>")
            en_lines.append(f"<p style='color:black;'> - 降車：{dropoff}</p>")
            en_lines.append(f"<p style='color:black;'> - 電話：{phone}</p>")
            en_lines.append(f"<p style='color:black;'> - メール：{guest_email}</p>")
        en_tail = "<p style='color:black;'>ご不明な点がございましたら (02-2691-9222 #1) までご連絡ください。</p>"
        second = "\n".join(en_lines) + en_tail
    elif lang == "ko":
        en_lines = []
        if typ == "cancel":
            en_lines.append(f"<p style='color:black;'>예약(번호: {booking_id})이(가) 성공적으로 취소되었습니다.</p>")
        else:
            en_lines.append(f"<p style='color:black;'>다음은 { '변경된' if typ=='modify' else '예약' } 상세 정보입니다.</p>")
            en_lines.append(f"<p style='color:black;'> - 예약번호: {booking_id}</p>")
            en_lines.append(f"<p style='color:black;'> - 시간: {time_hhmm} (GMT+8)</p>")
            en_lines.append(f"<p style='color:black;'> - 인원수: {passengers}</p>")
            en_lines.append(f"<p style='color:black;'> - 방향: {direction}</p>")
            en_lines.append(f"<p style='color:black;'> - 승차: {pickup}</p>")
            en_lines.append(f"<p style='color:black;'> - 하차: {dropoff}</p>")
            en_lines.append(f"<p style='color:black;'> - 전화: {phone}</p>")
            en_lines.append(f"<p style='color:black;'> - 이메일: {guest_email}</p>")
        en_tail = "<p style='color:black;'>문의사항이 있으시면 (02-2691-9222 #1) 로 연락해 주세요.</p>"
        second = "\n".join(en_lines) + en_tail
    else:
        en_lines = []
        if typ == "cancel":
            en_lines.append(f"<p style='color:black;'>Your reservation (Reservation Number: {booking_id}) has been successfully cancelled.</p>")
        else:
            en_lines.append(f"<p style='color:black;'>Here are your { 'updated' if typ=='modify' else 'reservation' } details:</p>")
            en_lines.append(f"<p style='color:black;'> - Reservation Number: {booking_id}</p>")
            en_lines.append(f"<p style='color:black;'> - Time: {time_hhmm} (GMT+8)</p>")
            en_lines.append(f"<p style='color:black;'> - Guests: {passengers}</p>")
            en_lines.append(f"<p style='color:black;'> - Direction: {direction}</p>")
            en_lines.append(f"<p style='color:black;'> - Pickup: {pickup}</p>")
            en_lines.append(f"<p style='color:black;'> - Dropoff: {dropoff}</p>")
            en_lines.append(f"<p style='color:black;'> - Phone: {phone}</p>")
            en_lines.append(f"<p style='color:black;'> - Email: {guest_email}</p>")
        en_tail = "<p style='color:black;'>If you have any questions, please contact us at (02-2691-9222 #1).</p>"
        second = "\n".join(en_lines) + en_tail

    return zh + "<br/><br/>" + second

def handle_email(d: Dict[str, Any]):
    typ = d.get("type","").lower()  # book / modify / cancel
    if typ not in ("book","modify","cancel"):
        raise HTTPException(status_code=400, detail="invalid type")
    to_email = d.get("email")
    if not to_email:
        raise HTTPException(status_code=400, detail="missing email")
    subject_map = {
        "book": "汐止福泰大飯店接駁車預約確認 / Forte Hotel Xizhi Shuttle Reservation Confirmation",
        "modify": "汐止福泰大飯店接駁車修改確認 / Forte Hotel Xizhi Shuttle Reservation Updated",
        "cancel": "汐止福泰大飯店接駁車取消確認 / Forte Hotel Xizhi Shuttle Reservation Cancellation",
    }
    subject = subject_map[typ]
    html = multilingual_body(d, typ)
    png_bytes = None
    ticket_png_dataurl = d.get("ticket_png")
    if ticket_png_dataurl and isinstance(ticket_png_dataurl, str) and ticket_png_dataurl.startswith("data:image/png;base64,"):
        png_bytes = base64.b64decode(ticket_png_dataurl.split(",",1)[1])
    # Send
    smtp_send_mail(to_email, subject, html, png_bytes)

    # Mark Y column
    booking_id = d.get("bookingId") or d.get("booking_id")
    if booking_id and SPREADSHEET_ID:
        try:
            ws, name_to_idx = get_sheet_and_header()
            name_to_idx = ensure_mail_sent_column(ws, name_to_idx)
            row_idx = find_row_by_booking_id(ws, name_to_idx, str(booking_id))
            if row_idx:
                mark_mail_sent(ws, name_to_idx, row_idx)
        except Exception:
            pass

    return {"status":"ok"}
