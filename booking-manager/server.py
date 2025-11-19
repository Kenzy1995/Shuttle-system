from __future__ import annotations
import io
import os
import re
import time
import base64
import logging
import threading
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple
import urllib.parse
import secrets  

import qrcode
from fastapi import FastAPI, HTTPException, Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, validator
import gspread
import google.auth
import hashlib
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.image import MIMEImage
from email.mime.base import MIMEBase
from email import encoders
from PIL import Image, ImageDraw, ImageFont

# Email settings
EMAIL_FROM_NAME = "汐止福泰大飯店"
EMAIL_FROM_ADDR = "fortehotels.shuttle@gmail.com"

# ========== 日誌設定 ==========
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("booking-manager")

# ========== 常數與工具 ==========
SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

# Spreadsheet identifiers
SPREADSHEET_ID = "1xp54tKOczklmT8uacW-HMxwV8r0VOR2ui33jYcE2pUQ"
SHEET_NAME_MAIN = "預約審核(櫃台)"      # 主資料表
SHEET_NAME_CAP  = "可預約班次(web)"     # 剩餘可預約名額（權威來源）

# Base URL for generating QR code images
BASE_URL = "https://booking-manager-995728097341.asia-east1.run.app"

# 表頭列開始索引（1-based indexing）
HEADER_ROW_MAIN = 2

# 狀態文本
BOOKED_TEXT = "✔️ 已預約 Booked"
CANCELLED_TEXT = "❌ 已取消 Cancelled"

# 主表允許欄位
HEADER_KEYS = {
    "申請日期", "最後操作時間", "預約編號", "往返", "日期", "班次", "車次",
    "上車地點", "下車地點", "姓名", "手機", "信箱", "預約人數", "櫃台審核",
    "預約狀態", "乘車狀態", "身分", "房號", "入住日期", "退房日期", "用餐日期",
    "上車索引", "下車索引", "涉及路段範圍", "QRCode編碼", "備註", "寄信狀態",
    "車次-日期時間","主班次時間","確認人數"
}

# 可預約班次表必要欄位
CAP_REQ_HEADERS = ["去程 / 回程", "日期", "班次", "站點", "可預約人數"]

# 站點索引
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

# ========== 工具函數 ==========
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
    return f"{int(m)}/{int(d)} {time_hm}"

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

def _compute_main_departure_datetime(direction: str, pickup: str, date_iso: str, time_hm: str) -> str:
    date_iso = (date_iso or "").strip()
    time_hm = _time_hm_from_any(time_hm or "")
    if not date_iso or not time_hm:
        return ""

    try:
        dt = datetime.strptime(f"{date_iso} {time_hm}", "%Y-%m-%d %H:%M")
    except Exception:
        return ""

    if direction != "回程":
        return dt.strftime("%Y/%m/%d %H:%M")

    p = (pickup or "").strip()
    offset_min = 0

    if "捷運" in p or "Exhibition Center" in p:
        offset_min = 5
    elif "火車" in p or "Train Station" in p:
        offset_min = 10
    elif "LaLaport" in p:
        offset_min = 20

    if offset_min:
        dt = dt - timedelta(minutes=offset_min)

    return dt.strftime("%Y/%m/%d %H:%M")

def _normalize_station_for_capacity(direction: str, pick: str, drop: str) -> str:
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


def _generate_booking_id_day_rand6(ws_main: gspread.Worksheet, today_iso: str) -> str:
    """
    產生 8 碼 booking_id：
    前 2 碼 = 今日「日」(01–31)
    後 6 碼 = 0–9 的亂數
    並且在目前主表資料裡確認「不重複」。
    不會額外多讀一次 Sheet（本來就會 get_all_values）。
    """
    m = header_map_main(ws_main)
    all_values = _read_all_rows(ws_main)  # 本來 _get_max_seq_for_date 就會做這行

    # 沒有「預約編號」欄位的 fallback：直接給一個亂數（理論上不會發生）
    if "預約編號" not in m:
        day_str = today_iso.split("-")[2]  # "YYYY-MM-DD" → 取最後兩位日
        rand_part = f"{secrets.randbelow(10**6):06d}"
        return day_str + rand_part

    c_id = m["預約編號"] - 1  # 0-based index
    day_str = today_iso.split("-")[2]      # 取「日」，例如 "2025-11-14" → "14"

    # 收集今天這一天前綴相同的既有 ID，避免撞號只需要跟「今天」比
    existing_for_today = set()
    for row in all_values[HEADER_ROW_MAIN:]:
        if c_id < len(row):
            bid = (row[c_id] or "").strip()
            if bid.startswith(day_str) and len(bid) == 8 and bid.isdigit():
                existing_for_today.add(bid)

    # 最多重試 20 次，理論上一次就會成功
    for _ in range(20):
        rand_part = f"{secrets.randbelow(10**6):06d}"  # 000000–999999
        booking_id = day_str + rand_part
        if booking_id not in existing_for_today:
            return booking_id

    # 理論上到不了這裡，如果真的到了就噴 500
    raise RuntimeError("booking_id_generation_failed")


# ========== 容量檢查 ==========
def _find_cap_header_row(values: List[List[str]]) -> int:
    for i in range(min(5, len(values))):
        row = [c.strip() for c in values[i]]
        if "去程 / 回程" in row and "可預約人數" in row:
            return i + 1
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

# ========== 改良的車票生成功能 ==========
def generate_ticket_image(booking_info: Dict[str, Any], qr_content: str, lang: str = "zh") -> str:
    """生成符合前端樣式的車票圖片"""
    try:
        # 創建圖片 - 調整尺寸以符合設計
        width, height = 400, 600
        image = Image.new('RGB', (width, height), '#FFFFFF')
        draw = ImageDraw.Draw(image)
        
        # 顏色定義
        primary_color = '#2c5aa0'
        secondary_color = '#666666'
        background_color = '#f8f9fa'
        
        # 嘗試加載字體
        try:
            title_font = ImageFont.truetype("arial.ttf", 20)
            header_font = ImageFont.truetype("arial.ttf", 16)
            normal_font = ImageFont.truetype("arial.ttf", 14)
            small_font = ImageFont.truetype("arial.ttf", 12)
        except:
            title_font = ImageFont.load_default()
            header_font = ImageFont.load_default()
            normal_font = ImageFont.load_default()
            small_font = ImageFont.load_default()
        
        # 標題區域
        draw.rectangle([0, 0, width, 60], fill=primary_color)
        
        # 標題文字
        title_text = "汐止福泰大飯店接駁車票"
        if lang == "en":
            title_text = "Forte Hotel Xizhi Shuttle Ticket"
        elif lang == "ja":
            title_text = "汐止フォルテホテル シャトルチケット"
        elif lang == "ko":
            title_text = "포르테 호텔 시즈 셔틀 티켓"
            
        draw.text((width//2, 30), title_text, fill='white', font=title_font, anchor="mm")
        
        # 基本信息區域
        y_pos = 80
        
        # 預約時間
        time_text = f"{booking_info.get('date', '')} {booking_info.get('time', '')}"
        draw.text((20, y_pos), "預約時間", fill=secondary_color, font=small_font)
        draw.text((20, y_pos + 20), time_text, fill='black', font=normal_font)
        y_pos += 50
        
        # 預約編號
        draw.text((20, y_pos), "預約編號", fill=secondary_color, font=small_font)
        draw.text((20, y_pos + 20), booking_info.get('booking_id', ''), fill='black', font=header_font)
        y_pos += 50
        
        # 方向
        direction_display = "去程 → 飯店" if booking_info.get('direction') == "去程" else "回程 ← 飯店"
        draw.text((20, y_pos), "方向", fill=secondary_color, font=small_font)
        draw.text((20, y_pos + 20), direction_display, fill=primary_color, font=normal_font)
        y_pos += 50
        
        # 站點信息
        pick_text = booking_info.get('pick', '')
        drop_text = booking_info.get('drop', '')
        
        # 上車地點
        draw.text((20, y_pos), "上車地點", fill=secondary_color, font=small_font)
        # 處理長文本換行
        if len(pick_text) > 20:
            pick_lines = [pick_text[i:i+20] for i in range(0, len(pick_text), 20)]
            for i, line in enumerate(pick_lines):
                draw.text((20, y_pos + 20 + i*20), line, fill='black', font=small_font)
            y_pos += 20 + len(pick_lines)*20
        else:
            draw.text((20, y_pos + 20), pick_text, fill='black', font=small_font)
            y_pos += 50
        
        # 下車地點
        draw.text((20, y_pos), "下車地點", fill=secondary_color, font=small_font)
        if len(drop_text) > 20:
            drop_lines = [drop_text[i:i+20] for i in range(0, len(drop_text), 20)]
            for i, line in enumerate(drop_lines):
                draw.text((20, y_pos + 20 + i*20), line, fill='black', font=small_font)
            y_pos += 20 + len(drop_lines)*20
        else:
            draw.text((20, y_pos + 20), drop_text, fill='black', font=small_font)
            y_pos += 50
        
        # 乘客信息
        draw.text((20, y_pos), "姓名", fill=secondary_color, font=small_font)
        draw.text((20, y_pos + 20), booking_info.get('name', ''), fill='black', font=normal_font)
        
        draw.text((200, y_pos), "電話", fill=secondary_color, font=small_font)
        draw.text((200, y_pos + 20), booking_info.get('phone', ''), fill='black', font=normal_font)
        y_pos += 50
        
        draw.text((20, y_pos), "信箱", fill=secondary_color, font=small_font)
        email_text = booking_info.get('email', '')
        if len(email_text) > 25:
            email_text = email_text[:25] + "..."
        draw.text((20, y_pos + 20), email_text, fill='black', font=small_font)
        
        draw.text((200, y_pos), "人數", fill=secondary_color, font=small_font)
        draw.text((200, y_pos + 20), f"{booking_info.get('pax', '')} 人", fill='black', font=normal_font)
        y_pos += 50
        
        # 生成QR碼
        qr_img = qrcode.make(qr_content)
        qr_size = 120
        qr_img = qr_img.resize((qr_size, qr_size))
        
        # 將QR碼放在右下角
        qr_x = width - qr_size - 20
        qr_y = height - qr_size - 20
        image.paste(qr_img, (qr_x, qr_y))
        
        # 底部提示文字
        footer_text = "請出示此車票乘車"
        if lang == "en":
            footer_text = "Please present this ticket for boarding"
        elif lang == "ja":
            footer_text = "このチケットを提示して乗車してください"
        elif lang == "ko":
            footer_text = "이 티켓을 제시하고 탑승하세요"
            
        draw.text((width//2, height - 60), footer_text, fill=primary_color, font=small_font, anchor="mm")
        
        # 邊框
        draw.rectangle([5, 5, width-5, height-5], outline=primary_color, width=2)
        
        # 轉換為base64
        buffer = io.BytesIO()
        image.save(buffer, format='PNG', quality=95)
        buffer.seek(0)
        img_str = base64.b64encode(buffer.getvalue()).decode()
        
        return img_str
        
    except Exception as e:
        log.error(f"生成車票圖片失敗: {str(e)}")
        # 返回一個簡單的錯誤圖片
        error_img = Image.new('RGB', (300, 100), 'white')
        draw = ImageDraw.Draw(error_img)
        draw.text((150, 50), "Ticket Generation Failed", fill='red', anchor="mm")
        buffer = io.BytesIO()
        error_img.save(buffer, format='PNG')
        buffer.seek(0)
        return base64.b64encode(buffer.getvalue()).decode()

# ========== 改良的流程控制 ==========
class BookingProcessor:
    def __init__(self):
        self.processing_lock = threading.Lock()
    
    def prepare_booking_row(self, p: BookPayload, booking_id: str, qr_content: str, headers: List[str], hmap: Dict[str, int]) -> List[str]:
        """準備預約資料行"""
        time_hm = _time_hm_from_any(p.time)
        car_display = _display_trip_str(p.date, time_hm)
        pk_idx, dp_idx, seg_str = _compute_indices_and_segments(p.pickLocation, p.dropLocation)
        
        # 計算車次時間
        date_obj = datetime.strptime(p.date, "%Y-%m-%d")
        car_datetime = date_obj.strftime("%Y/%m/%d") + " " + time_hm
        main_departure = _compute_main_departure_datetime(
            p.direction, p.pickLocation, p.date, time_hm
        )
        
        # 準備寫入行
        newrow = [""] * len(headers)
        identity_simple = "住宿" if p.identity == "hotel" else "用餐"
        
        def setv(row_arr: List[str], col: str, v: Any):
            if col in hmap and 1 <= hmap[col] <= len(row_arr):
                row_arr[hmap[col] - 1] = str(v)
        
        # 設置所有欄位
        setv(newrow, "申請日期", _tz_now_str())
        setv(newrow, "預約狀態", BOOKED_TEXT)
        setv(newrow, "預約編號", booking_id)
        setv(newrow, "往返", p.direction)
        setv(newrow, "日期", p.date)
        setv(newrow, "班次", time_hm)
        setv(newrow, "車次", car_display)
        setv(newrow, "車次-日期時間", car_datetime)
        setv(newrow, "主班次時間", main_departure)
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
        setv(newrow, "寄信狀態", "處理中")
        
        return newrow

booking_processor = BookingProcessor()

# ========== 改良的非同步處理 ==========
def _async_process_mail(
    kind: str,  # "book" / "modify" / "cancel"
    booking_id: str,
    booking_data: Dict[str, Any],
    qr_content: Optional[str],
    lang: str = "zh",
):
    """統一的背景寄信流程"""
    def _process():
        try:
            ws_main = open_ws(SHEET_NAME_MAIN)
            hmap = header_map_main(ws_main)
            headers = _sheet_headers(ws_main, HEADER_ROW_MAIN)

            # 找到對應的行
            rownos = _find_rows_by_pred(
                ws_main,
                headers,
                HEADER_ROW_MAIN,
                lambda r: r.get("預約編號") == booking_id,
            )
            if not rownos:
                log.error(f"[mail:{kind}] 找不到預約編號 {booking_id} 對應的行")
                return

            rowno = rownos[0]

            # 只在 book / modify 生成車票圖片
            ticket_base64: Optional[str] = None
            ticket_bytes: Optional[bytes] = None
            if kind in ("book", "modify") and qr_content:
                try:
                    ticket_base64 = generate_ticket_image(booking_data, qr_content, lang)
                    # 做成附件用的 bytes
                    try:
                        ticket_bytes = base64.b64decode(ticket_base64)
                    except Exception as e:
                        log.error(f"[mail:{kind}] 車票 base64 decode 失敗: {e}")
                        ticket_bytes = None
                except Exception as e:
                    log.error(f"[mail:{kind}] 生成車票圖片失敗: {e}")

            try:
                # HTML 內仍然可以放 inline 圖片（大多數信箱會顯示）
                subject, html_body = _compose_mail_html(
                    booking_data, lang, kind, ticket_base64
                )
                _send_email_gmail(
                    booking_data["email"],
                    subject,
                    html_body,
                    attachment=ticket_bytes,
                    attachment_filename=f"ticket_{booking_id}.png" if ticket_bytes else "ticket.png",
                )
                mail_status = f"{_tz_now_str()} 寄信成功({kind})"
                log.info(f"[mail:{kind}] 預約 {booking_id} 寄信成功")
            except Exception as e:
                mail_status = f"{_tz_now_str()} 寄信失敗({kind}): {str(e)}"
                log.error(f"[mail:{kind}] 預約 {booking_id} 寄信失敗: {str(e)}")

            # 更新寄信狀態
            if "寄信狀態" in hmap:
                ws_main.update_acell(
                    gspread.utils.rowcol_to_a1(rowno, hmap["寄信狀態"]),
                    mail_status,
                )

        except Exception as e:
            log.error(f"[mail:{kind}] 非同步處理預約 {booking_id} 時發生錯誤: {str(e)}")

    thread = threading.Thread(target=_process, daemon=True)
    thread.start()



def async_process_after_booking(
    booking_id: str,
    booking_data: Dict[str, Any],
    qr_content: str,
    lang: str = "zh",
):
    _async_process_mail("book", booking_id, booking_data, qr_content, lang)


def async_process_after_modify(
    booking_id: str,
    booking_data: Dict[str, Any],
    qr_content: Optional[str],
    lang: str = "zh",
):
    _async_process_mail("modify", booking_id, booking_data, qr_content, lang)


def async_process_after_cancel(
    booking_id: str,
    booking_data: Dict[str, Any],
    lang: str = "zh",
):
    # cancel 不需要 QR code / 車票
    _async_process_mail("cancel", booking_id, booking_data, qr_content=None, lang=lang)


# ========== Email 功能 ==========
def _send_email_gmail(
    to_email: str,
    subject: str,
    html_body: str,
    attachment: Optional[bytes] = None,
    attachment_filename: str = "ticket.png",
):
    """使用 SMTP 寄信"""
    host = os.getenv("SMTP_HOST", "smtp.gmail.com")
    port = int(os.getenv("SMTP_PORT", "587"))
    user = os.getenv("SMTP_USER") or EMAIL_FROM_ADDR
    password = os.getenv("SMTP_PASS")

    if not password:
        raise RuntimeError("SMTP_PASS 未設定，無法寄信")

    msg = MIMEMultipart()
    msg["To"] = to_email
    msg["From"] = f"{EMAIL_FROM_NAME} <{EMAIL_FROM_ADDR}>"
    msg["Subject"] = subject
    
    # HTML 內容
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    # 附件
    if attachment:
        part = MIMEBase("application", "octet-stream")
        part.set_payload(attachment)
        encoders.encode_base64(part)
        part.add_header(
            "Content-Disposition",
            f'attachment; filename="{attachment_filename}"',
        )
        msg.attach(part)

    # 連線 SMTP 寄信
    with smtplib.SMTP(host, port) as server:
        server.ehlo()
        server.starttls()
        server.ehlo()
        server.login(user, password)
        server.sendmail(EMAIL_FROM_ADDR, [to_email], msg.as_string())

def _compose_mail_html(
    info: Dict[str, str],
    lang: str,
    kind: str,
    ticket_base64: Optional[str] = None
) -> Tuple[str, str]:
    """組合郵件內容"""

    # 根據語言決定第二語言
    second_lang = "en"  # 預設英文
    if lang in ["ja", "ko"]:
        second_lang = lang

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

    # 雙語標題
    subject_zh = subjects[kind]["zh"]
    subject_second = subjects[kind].get(second_lang, subjects[kind]["en"])
    subject = f"{subject_zh} / {subject_second}"

    # 中文內容
    zh_content = f"""
    <div style="font-family: Arial, sans-serif; color: #333; line-height: 1.6;">
        <h2 style="color: #2c5aa0;">{subject_zh}</h2>
        <p>尊敬的 {info.get('name','')} 貴賓，您好！</p>
        <p>以下為您的接駁車預約資訊：</p>
        <div style="background: #f9f9f9; padding: 15px; border-radius: 5px; margin: 15px 0;">
            <ul style="list-style: none; padding: 0;">
                <li><strong>預約編號：</strong>{info.get('booking_id','')}</li>
                <li><strong>預約班次：</strong>{info.get('date','')} {info.get('time','')} (GMT+8)</li>
                <li><strong>預約人數：</strong>{info.get('pax','')}</li>
                <li><strong>往返方向：</strong>{info.get('direction','')}</li>
                <li><strong>上車站點：</strong>{info.get('pick','')}</li>
                <li><strong>下車站點：</strong>{info.get('drop','')}</li>
                <li><strong>手機：</strong>{info.get('phone','')}</li>
                <li><strong>信箱：</strong>{info.get('email','')}</li>
            </ul>
        </div>
    </div>
    """

    # 第二語言內容
    second_content_map = {
        "en": f"""
        <div style="margin-top: 30px; border-top: 2px solid #2c5aa0; padding-top: 20px;">
            <h2 style="color: #2c5aa0;">{subject_second}</h2>
            <p>Dear {info.get('name','')},</p>
            <p>Here are your shuttle reservation details:</p>
            <div style="background: #f9f9f9; padding: 15px; border-radius: 5px; margin: 15px 0;">
                <ul style="list-style: none; padding: 0;">
                    <li><strong>Reservation Number:</strong> {info.get('booking_id','')}</li>
                    <li><strong>Reservation Time:</strong> {info.get('date','')} {info.get('time','')} (GMT+8)</li>
                    <li><strong>Number of Guests:</strong> {info.get('pax','')}</li>
                    <li><strong>Direction:</strong> {info.get('direction','')}</li>
                    <li><strong>Pickup:</strong> {info.get('pick','')}</li>
                    <li><strong>Dropoff:</strong> {info.get('drop','')}</li>
                    <li><strong>Phone:</strong> {info.get('phone','')}</li>
                    <li><strong>Email:</strong> {info.get('email','')}</li>
                </ul>
            </div>
        </div>
        """,
        "ja": f"""
        <div style="margin-top: 30px; border-top: 2px solid #2c5aa0; padding-top: 20px;">
            <h2 style="color: #2c5aa0;">{subject_second}</h2>
            <p>{info.get('name','')} 様</p>
            <p>シャトル予約の詳細は以下の通りです。</p>
            <div style="background: #f9f9f9; padding: 15px; border-radius: 5px; margin: 15px 0;">
                <ul style="list-style: none; padding: 0;">
                    <li><strong>予約番号：</strong>{info.get('booking_id','')}</li>
                    <li><strong>便：</strong>{info.get('date','')} {info.get('time','')} (GMT+8)</li>
                    <li><strong>人数：</strong>{info.get('pax','')}</li>
                    <li><strong>方向：</strong>{info.get('direction','')}</li>
                    <li><strong>乗車：</strong>{info.get('pick','')}</li>
                    <li><strong>降車：</strong>{info.get('drop','')}</li>
                    <li><strong>電話：</strong>{info.get('phone','')}</li>
                    <li><strong>メール：</strong>{info.get('email','')}</li>
                </ul>
            </div>
        </div>
        """,
        "ko": f"""
        <div style="margin-top: 30px; border-top: 2px solid #2c5aa0; padding-top: 20px;">
            <h2 style="color: #2c5aa0;">{subject_second}</h2>
            <p>{info.get('name','')} 고객님,</p>
            <p>셔틀 예약 내역은 아래와 같습니다.</p>
            <div style="background: #f9f9f9; padding: 15px; border-radius: 5px; margin: 15px 0;">
                <ul style="list-style: none; padding: 0;">
                    <li><strong>예약번호:</strong> {info.get('booking_id','')}</li>
                    <li><strong>시간:</strong> {info.get('date','')} {info.get('time','')} (GMT+8)</li>
                    <li><strong>인원:</strong> {info.get('pax','')}</li>
                    <li><strong>방향:</strong> {info.get('direction','')}</li>
                    <li><strong>승차:</strong> {info.get('pick','')}</li>
                    <li><strong>하차:</strong> {info.get('drop','')}</li>
                    <li><strong>전화:</strong> {info.get('phone','')}</li>
                    <li><strong>이메일:</strong> {info.get('email','')}</li>
                </ul>
            </div>
        </div>
        """,
    }

    second_content = second_content_map.get(second_lang, second_content_map["en"])

    # 車票圖片（直接嵌入郵件內文，base64）
    ticket_html = ""
    if kind in ("book", "modify") and ticket_base64:
        data_uri = f"data:image/png;base64,{ticket_base64}"
        ticket_html = f"""
        <div style="margin: 20px 0; text-align: center;">
            <h3 style="color: #2c5aa0;">您的車票 / Your Ticket</h3>
            <div style="display: inline-block; border: 2px solid #2c5aa0; border-radius: 10px; padding: 10px; background: white;">
                <img src="{data_uri}" alt="Shuttle Ticket" style="max-width: 100%; height: auto;" />
            </div>
            <p style="color: #666; font-size: 14px; margin-top: 10px;">
                請出示此車票乘車 / Please present this ticket for boarding
            </p>
        </div>
        """


    # 聯繫信息
    contact_info = """
        <div style="margin-top: 20px; padding: 15px; background: #e8f4ff; border-radius: 5px;">
            <p><strong>聯繫資訊 / Contact Information:</strong></p>
            <p>如有任何問題，請致電 (02-2691-9222 #1)</p>
            <p>If you have questions, call (02-2691-9222 #1)</p>
            <p>汐止福泰大飯店 敬上 / Forte Hotel Xizhi</p>
        </div>
    """

    # 組合完整HTML
    html_body = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="utf-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
    </head>
    <body style="font-family: Arial, sans-serif; color: #333; line-height: 1.6; max-width: 800px; margin: 0 auto; padding: 20px;">
        {zh_content}
        {second_content}
        {ticket_html}
        {contact_info}
    </body>
    </html>
    """

    return subject, html_body

# ========== Pydantic Models ==========
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
    lang: str = Field("zh", pattern="^(zh|en|ja|ko)$")

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
    lang: str = Field("zh", pattern="^(zh|en|ja|ko)$")

class DeletePayload(BaseModel):
    booking_id: str
    lang: str = Field("zh", pattern="^(zh|en|ja|ko)$")

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

# ========== FastAPI ==========
app = FastAPI(title="Shuttle Ops API", version="1.6.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://hotel-web-995728097341.asia-east1.run.app",
        "https://hotel-web-3addcbkbgq-de.a.run.app",
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
                if isinstance(v, (int, float)):
                  row_arr[hmap[col] - 1] = v
                elif isinstance(v, str):
                  row_arr[hmap[col] - 1] = v
                else:
                  row_arr[hmap[col] - 1] = str(v)

        def get_by_rowno(rowno: int, key: str) -> str:
            if key not in hmap:
                return ""
            return ws_main.cell(rowno, hmap[key]).value or ""

        # ===== 新增預約 =====
        if action == "book":
            p = BookPayload(**data)

            # 先拿班次時間
            time_hm = _time_hm_from_any(p.time)

            # 容量檢查（可預約班次表是權威：可預約人數 = 現存剩餘數）
            station_for_cap = _normalize_station_for_capacity(
                p.direction, p.pickLocation, p.dropLocation
            )
            rem = lookup_capacity(p.direction, p.date, time_hm, station_for_cap)
            if int(p.passengers) > int(rem):
                raise HTTPException(409, f"capacity_exceeded:{p.passengers}>{rem}")

            # 產生預約編號：以「今日日期」為準
            today_iso = _today_iso_taipei()
            booking_id = _generate_booking_id_day_rand6(ws_main, today_iso)

            # QR 內容
            em6 = _email_hash6(p.email)
            qr_content = f"FT:{booking_id}:{em6}"
            qr_url = f"{BASE_URL}/api/qr/{urllib.parse.quote(qr_content)}"

            # 用 BookingProcessor 統一產生 row（包含主班次時間、車次-日期時間...）
            newrow = booking_processor.prepare_booking_row(
                p, booking_id, qr_content, headers, hmap
            )

            # 寫入 Google Sheet（關鍵操作）
            ws_main.append_row(newrow, value_input_option="USER_ENTERED")
            log.info(f"book appended booking_id={booking_id}")

            # 立即回覆前端 —— 只給前端需要的東西，其他由前端自己維護
            response_data = {
                "status": "success",
                # 給前端用的 camelCase
                "bookingId": booking_id,
                "qrUrl": qr_url,
                "qrContent": qr_content,
                # 順便保留原本的 snake_case，避免前端還沒改完
                "booking_id": booking_id,
                "qr_url": qr_url,
                "qr_content": qr_content,
            }

            # 後端背景寄信（含車票圖片）
            booking_info = {
                "booking_id": booking_id,
                "date": p.date,
                "time": time_hm,
                "direction": p.direction,
                "pick": p.pickLocation,
                "drop": p.dropLocation,
                "name": p.name,
                "phone": p.phone,
                "email": p.email,
                "pax": str(p.passengers),
                "qr_content": qr_content,
                "qr_url": qr_url,
                
            }
            async_process_after_booking(booking_id, booking_info, qr_content, p.lang)

            return response_data


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
            now = datetime.now()
            one_month_ago = now - timedelta(days=31)
            results: List[Dict[str, str]] = []
            for row in all_values[HEADER_ROW_MAIN:]:
                # Always derive date/time from unified 車次-日期時間 column if available
                car_dt_str = get(row, "車次-日期時間")
                date_iso: str = ""
                time_hm: str = ""
                if car_dt_str:
                    try:
                        parts = car_dt_str.strip().split()
                        if parts:
                            date_iso = parts[0].replace("/", "-")
                            if len(parts) > 1:
                                time_hm = _time_hm_from_any(parts[1])
                        else:
                            date_iso = ""
                    except Exception:
                        # fallback to legacy columns
                        date_iso = get(row, "日期")
                        time_hm = _time_hm_from_any(get(row, "班次"))
                else:
                    date_iso = get(row, "日期")
                    time_hm = _time_hm_from_any(get(row, "班次"))
                # parse date to filter range; if invalid, use current time to avoid filtering out
                try:
                    d = datetime.strptime(date_iso, "%Y-%m-%d")
                except Exception:
                    d = now
                if d < one_month_ago:
                    continue
                # filter by id/phone/email
                if p.booking_id and p.booking_id != get(row, "預約編號"):
                    continue
                if p.phone and p.phone != get(row, "手機"):
                    continue
                if p.email and p.email != get(row, "信箱"):
                    continue
                rec = {k: get(row, k) for k in hmap}
                # override date/time fields with values derived from 車次-日期時間
                if date_iso:
                    rec["日期"] = date_iso
                if time_hm:
                    rec["班次"] = time_hm
                    # update 車次欄以新的顯示格式
                    rec["車次"] = _display_trip_str(date_iso, time_hm)
                # 如果櫃檯審核為 n 則將預約狀態標為「已拒絕」
                if rec.get("櫃台審核", "").lower() == "n":
                    rec["預約狀態"] = "已拒絕"
                results.append(rec)
            log.info(f"query results count={len(results)}")
            return results

        # ===== 修改 =====
        elif action == "modify":
            p = ModifyPayload(**data)

            # 找到目標列
            rownos = _find_rows_by_pred(
                ws_main,
                headers,
                HEADER_ROW_MAIN,
                lambda r: r.get("預約編號") == p.booking_id,
            )
            if not rownos:
                raise HTTPException(404, "找不到此預約編號")
            rowno = rownos[0]

            # 讀舊值
            old_dir = get_by_rowno(rowno, "往返")
            old_date = get_by_rowno(rowno, "日期")

            # 舊時間優先從「車次-日期時間」推回來
            old_car_dt = get_by_rowno(rowno, "車次-日期時間")
            if old_car_dt:
                parts = old_car_dt.strip().split()
                old_time = _time_hm_from_any(parts[1] if len(parts) > 1 else parts[0])
            else:
                old_time = _time_hm_from_any(get_by_rowno(rowno, "班次"))

            old_pick = get_by_rowno(rowno, "上車地點")
            old_drop = get_by_rowno(rowno, "下車地點")

            # 舊的人數：優先用確認人數
            try:
                confirm_pax = (get_by_rowno(rowno, "確認人數") or "").strip()
                if confirm_pax:
                    old_pax = int(confirm_pax)
                else:
                    old_pax = int(get_by_rowno(rowno, "預約人數") or "1")
            except Exception:
                old_pax = 1

            # 新值（沒給就用舊值）
            new_dir = p.direction or old_dir
            new_date = p.date or old_date
            new_time = _time_hm_from_any(p.time or old_time)
            new_pick = p.pickLocation or old_pick
            new_drop = p.dropLocation or old_drop
            new_pax = int(p.passengers if p.passengers is not None else old_pax)

            # 容量檢查
            station_for_cap_new = _normalize_station_for_capacity(new_dir, new_pick, new_drop)
            rem = lookup_capacity(new_dir, new_date, new_time, station_for_cap_new)

            # 如果還是同一班次，只需檢查增加的差額
            same_trip = (
                new_dir,
                new_date,
                new_time,
                _normalize_station_for_capacity(old_dir, old_pick, old_drop),
            ) == (
                old_dir,
                old_date,
                _time_hm_from_any(old_time),
                _normalize_station_for_capacity(old_dir, old_pick, old_drop),
            )

            if same_trip:
                delta = new_pax - old_pax
                if delta > 0 and delta > rem:
                    raise HTTPException(409, f"capacity_exceeded_delta:{delta}>{rem}")
            else:
                if new_pax > rem:
                    raise HTTPException(409, f"capacity_exceeded:{new_pax}>{rem}")

            # 開始組更新欄位
            updates: Dict[str, str] = {}
            time_hm = new_time
            car_display = _display_trip_str(new_date, time_hm) if (new_date and time_hm) else None

            # 更新 unified 車次-日期時間 + 主班次時間
            if new_date and new_time:
                date_obj = datetime.strptime(new_date, "%Y-%m-%d")
                car_datetime = date_obj.strftime("%Y/%m/%d") + " " + new_time
                updates["車次-日期時間"] = car_datetime

                main_departure = _compute_main_departure_datetime(
                    new_dir,
                    new_pick,
                    new_date,
                    new_time,
                )
                updates["主班次時間"] = main_departure

            # 站點索引 / 涉及路段
            pk_idx = dp_idx = None
            seg_str = None
            if new_pick and new_drop:
                pk_idx, dp_idx, seg_str = _compute_indices_and_segments(new_pick, new_drop)

            updates["預約狀態"] = BOOKED_TEXT
            updates["預約人數"] = str(new_pax)

            # 備註增加一條「已修改」
            if "備註" in hmap:
                current_note = ws_main.cell(rowno, hmap["備註"]).value or ""
                new_note = f"{_tz_now_str()} 已修改"
                updates["備註"] = f"{current_note}; {new_note}" if current_note else new_note

            updates["往返"] = new_dir
            updates["日期"] = new_date
            if time_hm:
                updates["班次"] = time_hm
            if car_display:
                updates["車次"] = car_display
            updates["上車地點"] = new_pick
            updates["下車地點"] = new_drop

            if p.phone:
                updates["手機"] = p.phone

            # 信箱 & QRCode 一律用「最終 email」計算
            old_email = get_by_rowno(rowno, "信箱")
            final_email = p.email or old_email
            qr_content: Optional[str] = None
            if p.email:
                updates["信箱"] = p.email
            if final_email:
                em6 = _email_hash6(final_email)
                qr_content = f"FT:{p.booking_id}:{em6}"
                updates["QRCode編碼"] = qr_content

            if pk_idx is not None:
                updates["上車索引"] = str(pk_idx)
            if dp_idx is not None:
                updates["下車索引"] = str(dp_idx)
            if seg_str is not None:
                updates["涉及路段範圍"] = seg_str

            if "最後操作時間" in hmap:
                updates["最後操作時間"] = _tz_now_str() + " 已修改"

            # 寄信狀態改為處理中
            updates["寄信狀態"] = "處理中"

            # 寫回 Google Sheet（batch_update）
            batch_updates = []
            for col_name, value in updates.items():
                if col_name in hmap:
                    batch_updates.append(
                        {
                            "range": gspread.utils.rowcol_to_a1(rowno, hmap[col_name]),
                            "values": [[value]],
                        }
                    )
            if batch_updates:
                ws_main.batch_update(batch_updates, value_input_option="USER_ENTERED")

            log.info(f"modify updated booking_id={p.booking_id}")

            # 立即回覆前端
            response_data = {
                "status": "success",
                "bookingId": p.booking_id,
                "booking_id": p.booking_id,
            }

            # 背景寄信
            booking_info = {
                "booking_id": p.booking_id,
                "date": new_date,
                "time": new_time,
                "direction": new_dir,
                "pick": new_pick,
                "drop": new_drop,
                "name": get_by_rowno(rowno, "姓名"),
                "phone": p.phone or get_by_rowno(rowno, "手機"),
                "email": final_email,
                "pax": str(new_pax),
                "qr_content": qr_content,
                "qr_url": f"{BASE_URL}/api/qr/{urllib.parse.quote(qr_content)}" if qr_content else "",
            }
            async_process_after_modify(p.booking_id, booking_info, qr_content, p.lang)

            return response_data


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
            
            # 設置寄信狀態為處理中
            updates["寄信狀態"] = "處理中"
            
            batch_updates = []
            for col_name, value in updates.items():
                if col_name in hmap:
                    batch_updates.append({
                        'range': gspread.utils.rowcol_to_a1(rowno, hmap[col_name]),
                        'values': [[value]]
                    })
            if batch_updates:
                ws_main.batch_update(batch_updates, value_input_option="USER_ENTERED")
            log.info(f"delete updated booking_id={p.booking_id}")
            
            # 立即回覆前端
            response_data = {"status": "success", "booking_id": p.booking_id}
            
            # 非同步處理寄信（取消不需要車票）
            booking_info = {
                "booking_id": p.booking_id,
                "date": get_by_rowno(rowno, "日期"),
                "time": _time_hm_from_any(get_by_rowno(rowno, "班次")),
                "direction": get_by_rowno(rowno, "往返"),
                "pick": get_by_rowno(rowno, "上車地點"),
                "drop": get_by_rowno(rowno, "下車地點"),
                "name": get_by_rowno(rowno, "姓名"),
                "phone": get_by_rowno(rowno, "手機"),
                "email": get_by_rowno(rowno, "信箱"),
                "pax": (
                    get_by_rowno(rowno, "確認人數")
                    or get_by_rowno(rowno, "預約人數")
                    or "1"
                ),
            }
            async_process_after_cancel(p.booking_id, booking_info, p.lang)
            
            return response_data

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
                ws_main.batch_update(batch_updates, value_input_option="USER_ENTERED")
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
                "time": _time_hm_from_any(get("班次")),
                "direction": get("往返"),
                "pick": get("上車地點"),
                "drop": get("下車地點"),
                "name": get("姓名"),
                "phone": get("手機"),
                "email": get("信箱"),
                "pax": (get("確認人數") or get("預約人數") or "1"),
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
