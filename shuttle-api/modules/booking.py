"""
預約管理模組
處理預約相關的所有功能：book, modify, cancel, query
"""
import logging
import re
import time
import hashlib
import secrets
import threading
import urllib.parse
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

import qrcode
import io
from fastapi import HTTPException

import config
from modules import firebase, sheets, cache, utils
import gspread

logger = logging.getLogger("shuttle-api.booking")


# ========== 預約 ID 生成 ==========
def generate_booking_id(today_iso: str) -> str:
    """
    產生 booking_id（日期 + 序號），使用 Firebase RTDB 交易確保原子性
    格式：YYMMDD + 序號（至少 2 位，不足補 0；超過 99 自動擴位）
    """
    if not firebase.init_firebase():
        raise RuntimeError("firebase_init_failed")
    
    date_key = (today_iso or "").strip()
    # YYMMDD
    parts = date_key.split("-")
    yymmdd = ""
    if len(parts) == 3:
        yy = int(parts[0]) % 100
        yymmdd = f"{yy:02d}{int(parts[1]):02d}{int(parts[2]):02d}"
    else:
        compact = date_key.replace("-", "")
        yymmdd = compact[-6:] if len(compact) >= 6 else compact
    
    ref = firebase.get_reference(f"/booking_seq/{date_key}")
    
    def txn(current):
        cur = int(current or 0)
        return cur + 1
    
    seq = ref.transaction(txn)
    try:
        seq_int = int(seq or 0)
    except Exception:
        seq_int = 0
    return f"{yymmdd}{seq_int:02d}"


# ========== 容量檢查 ==========
def find_cap_header_row(values: List[List[str]]) -> int:
    """找到可預約班次表的表頭行"""
    for i in range(min(5, len(values))):
        row = [c.strip() for c in values[i]]
        if "去程 / 回程" in row and "可預約人數" in row:
            return i + 1
    return 1


def cap_header_map(values: List[List[str]]) -> Tuple[Dict[str, int], int]:
    """獲取可預約班次表的表頭映射"""
    hdr_row = find_cap_header_row(values)
    headers = [c.strip() for c in (values[hdr_row - 1] if len(values) >= hdr_row else [])]
    m: Dict[str, int] = {}
    for idx, name in enumerate(headers, start=1):
        if name in config.CAP_REQ_HEADERS and name not in m:
            m[name] = idx
    return m, hdr_row


def col_letter(col_idx: int) -> str:
    """將列索引轉換為字母（A, B, C...）"""
    return gspread.utils.rowcol_to_a1(1, col_idx).replace("1", "")


def normalize_text(s: str) -> str:
    """正規化文字（去除多餘空格）"""
    return " ".join((s or "").replace("　", " ").split())


def parse_available(s: str) -> Optional[int]:
    """從字串中解析可預約人數"""
    if s is None:
        return None
    m = re.search(r"(\d+)", str(s))
    return int(m.group(1)) if m else None


def lookup_capacity(direction: str, date_iso: str, time_hm: str, station: str) -> int:
    """查找指定班次和站點的可預約人數"""
    values, m, hdr_row = sheets.get_cap_sheet_data()
    
    for key in config.CAP_REQ_HEADERS:
        if key not in m:
            raise HTTPException(409, f"capacity_header_missing:{key}")
    
    idx_dir = m["去程 / 回程"] - 1
    idx_date = m["日期"] - 1
    idx_time = m["班次"] - 1
    idx_st = m["站點"] - 1
    idx_avail = m["可預約人數"] - 1
    
    want_dir = normalize_text(direction)
    want_date = date_iso.strip()
    want_time = utils.time_hm_from_any(time_hm)
    want_station = normalize_text(station)
    
    for row in values[hdr_row:]:
        if not any(row):
            continue
        r_dir = normalize_text(row[idx_dir] if idx_dir < len(row) else "")
        r_date = (row[idx_date] if idx_date < len(row) else "").strip()
        r_time = utils.time_hm_from_any(row[idx_time] if idx_time < len(row) else "")
        r_st = normalize_text(row[idx_st] if idx_st < len(row) else "")
        r_avail = row[idx_avail] if idx_avail < len(row) else ""
        
        if r_dir == want_dir and r_date == want_date and r_time == want_time and r_st == want_station:
            avail = parse_available(r_avail)
            if avail is None:
                raise HTTPException(409, "capacity_not_numeric")
            return avail
    
    raise HTTPException(409, "capacity_not_found")


# ========== Firebase 併發鎖 ==========
def lock_id_for_capacity(date_iso: str, time_hm: str) -> str:
    """生成容量鎖的 ID"""
    raw = f"{date_iso}|{utils.time_hm_from_any(time_hm)}"
    h = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]
    return f"cap_{h}"


def acquire_capacity_lock(
    lock_id: str, date_iso: str, time_hm: str, timeout_s: int = config.LOCK_WAIT_SECONDS
) -> Optional[str]:
    """獲取容量鎖"""
    if not firebase.init_firebase():
        return None
    
    ref = firebase.get_reference(f"/sheet_locks/{lock_id}")
    holder = secrets.token_hex(8)
    start = time.monotonic()
    stale_ms = config.LOCK_STALE_SECONDS * 1000
    lock_date = (date_iso or "").strip()
    lock_time = utils.time_hm_from_any(time_hm)
    logger.info(f"[cap_lock] wait_start lock_id={lock_id} date={lock_date} time={lock_time}")
    poll_no = 0
    
    while (time.monotonic() - start) < timeout_s:
        now_ms = int(time.time() * 1000)
        poll_no += 1
        
        def txn(current):
            if current is None:
                return {"holder": holder, "ts": now_ms, "date": lock_date, "time": lock_time}
            if isinstance(current, dict) and current.get("released") is True:
                return {"holder": holder, "ts": now_ms, "date": lock_date, "time": lock_time}
            cur_ts = int(current.get("ts", 0)) if isinstance(current, dict) else 0
            if cur_ts and (now_ms - cur_ts) > stale_ms:
                return {"holder": holder, "ts": now_ms, "date": lock_date, "time": lock_time}
            return current
        
        try:
            result = ref.transaction(txn)
            if isinstance(result, dict) and result.get("holder") == holder:
                waited_ms = int((time.monotonic() - start) * 1000)
                logger.info(
                    f"[cap_lock] acquired lock_id={lock_id} holder={holder} waited_ms={waited_ms} date={lock_date} time={lock_time}"
                )
                return holder
            if isinstance(result, dict):
                seen_holder = result.get("holder")
                seen_ts = result.get("ts")
                seen_date = result.get("date")
                seen_time = result.get("time")
                logger.info(
                    f"[cap_lock] poll={poll_no} lock_id={lock_id} seen_holder={seen_holder} seen_ts={seen_ts} "
                    f"seen_date={seen_date} seen_time={seen_time} now_ms={now_ms} stale_ms={stale_ms}"
                )
            else:
                logger.info(f"[cap_lock] poll={poll_no} lock_id={lock_id} seen_non_dict={result} now_ms={now_ms}")
        except Exception as e:
            logger.warning(
                f"[cap_lock] poll_error lock_id={lock_id} holder={holder} poll={poll_no} type={type(e).__name__} msg={e}"
            )
        
        time.sleep(0.2)
    
    waited_ms = int((time.monotonic() - start) * 1000)
    logger.warning(
        f"[cap_lock] timeout lock_id={lock_id} holder={holder} waited_ms={waited_ms} date={lock_date} time={lock_time}"
    )
    return None


def release_capacity_lock(lock_id: str, holder: str):
    """釋放容量鎖"""
    if not holder:
        return
    if not firebase.init_firebase():
        return
    
    ref = firebase.get_reference(f"/sheet_locks/{lock_id}")
    now_ms = int(time.time() * 1000)
    
    def txn(current):
        if isinstance(current, dict) and current.get("holder") == holder:
            current["released"] = True
            current["released_by"] = holder
            current["released_ts"] = now_ms
            return current
        if current is None:
            return {"released": True, "released_by": holder, "released_ts": now_ms, "ts": 0}
        return current
    
    try:
        result = ref.transaction(txn)
        logger.info(f"[cap_lock] released lock_id={lock_id} holder={holder} ts={now_ms} txn_result={result}")
    except Exception as e:
        logger.warning(f"[cap_lock] release_error lock_id={lock_id} holder={holder} type={type(e).__name__} msg={e}")


def finalize_capacity_lock(
    lock_id: str,
    holder: str,
    direction: str,
    date_iso: str,
    time_hm: str,
    station: str,
    expected_max: int,
):
    """完成容量鎖處理（等待容量重新計算後釋放鎖）"""
    try:
        cache.invalidate_cap_cache()
        wait_capacity_recalc(direction, date_iso, time_hm, station, expected_max)
    except Exception as e:
        logger.warning(f"[cap_wait] finalize_error type={type(e).__name__} msg={e}")
    finally:
        release_capacity_lock(lock_id, holder)


def wait_capacity_recalc(
    direction: str,
    date_iso: str,
    time_hm: str,
    station: str,
    expected_max: int,
    timeout_s: int = config.LOCK_WAIT_SECONDS,
) -> Tuple[bool, Optional[int]]:
    """等待容量重新計算"""
    start = time.monotonic()
    last_seen = None
    polls = 0
    logger.info(
        f"[cap_wait] start dir={direction} date={date_iso} time={time_hm} station={station} expected_max={expected_max}"
    )
    
    while (time.monotonic() - start) < timeout_s:
        cache.invalidate_cap_cache()
        try:
            last_seen = lookup_capacity(direction, date_iso, time_hm, station)
            polls += 1
            logger.info(f"[cap_wait] poll={polls} last_seen={last_seen} expected_max={expected_max}")
            if last_seen <= expected_max:
                logger.info(f"[cap_wait] done polls={polls} last_seen={last_seen} expected_max={expected_max}")
                return True, last_seen
        except HTTPException as e:
            detail = getattr(e, "detail", "") or ""
            if isinstance(detail, str) and "capacity_not_found" in detail:
                last_seen = 0
                if last_seen <= expected_max:
                    logger.info(f"[cap_wait] done_not_found polls={polls} last_seen=0 expected_max={expected_max}")
                    return True, last_seen
            else:
                last_seen = None
        except Exception as e:
            last_seen = None
            logger.warning(
                f"[cap_wait] poll_error type={type(e).__name__} msg={e} dir={direction} date={date_iso} time={time_hm} station={station}"
            )
            time.sleep(max(config.LOCK_POLL_INTERVAL, 5.0))
            continue
        time.sleep(config.LOCK_POLL_INTERVAL)
    
    logger.warning(f"[cap_wait] timeout polls={polls} last_seen={last_seen} expected_max={expected_max}")
    return False, last_seen


# ========== QR Code 生成 ==========
def generate_qr_code_image(qr_content: str) -> bytes:
    """生成 QR Code 圖片（PNG 格式）"""
    qr = qrcode.QRCode(version=1, box_size=10, border=5)
    qr.add_data(qr_content)
    qr.make(fit=True)
    
    img = qr.make_image(fill_color="black", back_color="white")
    img_bytes = io.BytesIO()
    img.save(img_bytes, format="PNG")
    return img_bytes.getvalue()


# ========== Email 功能 ==========
def compose_mail_text(info: Dict[str, str], lang: str, kind: str) -> Tuple[str, str]:
    """組合純文字郵件內容 - 雙語版本"""
    direction_map = {
        "zh": {"去程": "去程", "回程": "回程"},
        "en": {"去程": "Departure", "回程": "Return"},
        "ja": {"去程": "往路", "回程": "復路"},
        "ko": {"去程": "가는편", "回程": "오는편"},
    }
    raw_direction = info.get("direction", "")
    second_lang = lang if lang in ["en", "ja", "ko"] else "en"
    direction_zh = direction_map.get("zh", {}).get(raw_direction, raw_direction)
    direction_second = direction_map.get(second_lang, {}).get(raw_direction, raw_direction)
    
    subjects = {
        "book": {
            "zh": "汐止福泰大飯店接駁車預約確認",
            "en": "Forte Hotel Xizhi Shuttle Reservation Confirmation",
            "ja": "汐止フォルテホテル シャトル予約確認",
            "ko": "포르테 호텔 시즈 셔틀 예약 확인",
        },
        "modify": {
            "zh": "汐止福泰大飯店接駁車預約變更確認",
            "en": "Forte Hotel Xizhi Shuttle Reservation Updated",
            "ja": "汐止フォルテホテル シャトル予約変更完了",
            "ko": "포르테 호텔 시즈 셔틀 예약 변경 완료",
        },
        "cancel": {
            "zh": "汐止福泰大飯店接駁車預約已取消",
            "en": "Forte Hotel Xizhi Shuttle Reservation Canceled",
            "ja": "汐止フォルテホテル シャトル予約キャンセル",
            "ko": "포르테 호텔 시즈 셔틀 예약 취소됨",
        },
    }
    
    subject_zh = subjects[kind]["zh"]
    subject_second = subjects[kind].get(lang, subjects[kind]["en"])
    subject = f"{subject_zh} / {subject_second}"
    
    # 中文內容
    chinese_content = f"""
尊敬的 {info.get('name','')} 貴賓，您好！

您的接駁車預約資訊：

預約編號：{info.get('booking_id','')}
預約班次：{info.get('date','')} {info.get('time','')} (GMT+8)
預約人數：{info.get('pax','')}
往返方向：{direction_zh}
上車站點：{info.get('pick','')}
下車站點：{info.get('drop','')}
手機：{info.get('phone','')}
信箱：{info.get('email','')}

請出示附件中的 QR Code 車票乘車。

如有任何問題，請致電 (02-2691-9222 #1)

汐止福泰大飯店 敬上
"""
    
    # 第二語言內容
    second_content_map = {
        "en": f"""
Dear {info.get('name','')},

Your shuttle reservation details:

Reservation Number: {info.get('booking_id','')}
Reservation Time: {info.get('date','')} {info.get('time','')} (GMT+8)
Number of Guests: {info.get('pax','')}
Direction: {direction_second}
Pickup Location: {info.get('pick','')}
Dropoff Location: {info.get('drop','')}
Phone: {info.get('phone','')}
Email: {info.get('email','')}

Please present the attached QR code ticket for boarding.

If you have any questions, please call (02-2691-9222 #1)

Best regards,
Forte Hotel Xizhi
""",
        "ja": f"""
{info.get('name','')} 様

シャトル予約の詳細：

予約番号：{info.get('booking_id','')}
便：{info.get('date','')} {info.get('time','')} (GMT+8)
人数：{info.get('pax','')}
方向：{direction_second}
乗車：{info.get('pick','')}
降車：{info.get('drop','')}
電話：{info.get('phone','')}
メール：{info.get('email','')}

添付のQRコードチケットを提示して乗車してください。

ご質問があれば、(02-2691-9222 #1) までお電話ください。

汐止フルオンホテル
""",
        "ko": f"""
{info.get('name','')} 고객님,

셔틀 예약 내역：

예약번호: {info.get('booking_id','')}
시간: {info.get('date','')} {info.get('time','')} (GMT+8)
인원: {info.get('pax','')}
방향: {direction_second}
승차: {info.get('pick','')}
하차: {info.get('drop','')}
전화: {info.get('phone','')}
이메일: {info.get('email','')}

첨부된 QR 코드 티켓을 제시하고 탑승하세요.

문의사항이 있으면 (02-2691-9222 #1) 로 전화주세요.

포르테 호텔 시즈
"""
    }
    
    second_content = second_content_map.get(second_lang, second_content_map["en"])
    separator = "\n" + "=" * 50 + "\n"
    text_body = chinese_content + separator + second_content
    
    return subject, text_body


# ========== Email 發送 ==========
def send_email(
    to_email: str,
    subject: str,
    text_body: str,
    attachment: Optional[bytes] = None,
    attachment_filename: str = "ticket.png",
):
    """使用 SMTP 寄信"""
    import smtplib
    from email.mime.multipart import MIMEMultipart
    from email.mime.text import MIMEText
    from email.mime.base import MIMEBase
    from email import encoders
    
    host = config.SMTP_HOST
    port = config.SMTP_PORT
    user = config.EMAIL_FROM_ADDR
    password = config.SMTP_PASSWORD
    
    if not password:
        raise RuntimeError("SMTP_PASSWORD 未設定，無法寄信")
    
    msg = MIMEMultipart()
    msg["To"] = to_email
    msg["From"] = f"{config.EMAIL_FROM_NAME} <{config.EMAIL_FROM_ADDR}>"
    msg["Subject"] = subject
    
    # 純文字內容
    msg.attach(MIMEText(text_body, "plain", "utf-8"))
    
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
        server.sendmail(config.EMAIL_FROM_ADDR, [to_email], msg.as_string())


# ========== 預約行準備 ==========
def prepare_booking_row(
    p: Dict[str, Any],
    booking_id: str,
    qr_content: str,
    headers: List[str],
    hmap: Dict[str, int],
) -> List[str]:
    """準備預約資料行"""
    time_hm = utils.time_hm_from_any(p.get("time", ""))
    car_display = utils.display_trip_str(p.get("date", ""), time_hm)
    pk_idx, dp_idx, seg_str = utils.compute_indices_and_segments(
        p.get("pickLocation", ""), p.get("dropLocation", "")
    )
    
    # 計算車次時間
    date_str = p.get("date", "")
    car_datetime = ""
    if date_str and time_hm:
        try:
            date_obj = datetime.strptime(date_str, "%Y-%m-%d")
            car_datetime = date_obj.strftime("%Y/%m/%d") + " " + time_hm
        except Exception:
            pass
    
    main_departure = utils.compute_main_departure_datetime(
        p.get("direction", ""), p.get("pickLocation", ""), date_str, time_hm
    )
    
    # 準備寫入行
    newrow = [""] * len(headers)
    identity_simple = "住宿" if p.get("identity") == "hotel" else "用餐"
    
    def setv(row_arr: List[str], col: str, v: Any):
        if col in hmap and 1 <= hmap[col] <= len(row_arr):
            row_arr[hmap[col] - 1] = str(v)
    
    # 設置所有欄位
    setv(newrow, "申請日期", utils.tz_now_str())
    setv(newrow, "預約狀態", config.BOOKED_TEXT)
    setv(newrow, "預約編號", booking_id)
    setv(newrow, "往返", p.get("direction", ""))
    setv(newrow, "日期", date_str)
    setv(newrow, "班次", time_hm)
    setv(newrow, "車次", car_display)
    setv(newrow, "車次-日期時間", car_datetime)
    setv(newrow, "主班次時間", main_departure)
    setv(newrow, "上車地點", p.get("pickLocation", ""))
    setv(newrow, "下車地點", p.get("dropLocation", ""))
    setv(newrow, "姓名", p.get("name", ""))
    setv(newrow, "手機", p.get("phone", ""))
    setv(newrow, "信箱", p.get("email", ""))
    setv(newrow, "預約人數", p.get("passengers", 1))
    setv(newrow, "乘車狀態", "")
    setv(newrow, "身分", identity_simple)
    setv(newrow, "房號", p.get("roomNumber") or "")
    setv(newrow, "入住日期", p.get("checkIn") or "")
    setv(newrow, "退房日期", p.get("checkOut") or "")
    setv(newrow, "用餐日期", p.get("diningDate") or "")
    setv(newrow, "上車索引", pk_idx)
    setv(newrow, "下車索引", dp_idx)
    setv(newrow, "涉及路段範圍", seg_str)
    setv(newrow, "QRCode編碼", qr_content)
    setv(newrow, "寄信狀態", "處理中")
    
    return newrow


# ========== Email Hash ==========
def email_hash6(email: str) -> str:
    """生成 Email 的 6 位雜湊值"""
    return hashlib.sha256((email or "").encode("utf-8")).hexdigest()[:6]

