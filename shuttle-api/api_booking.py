"""
預約操作 API 實現
完整的 /api/ops 端點處理邏輯
"""
import logging
import urllib.parse
import base64
import threading
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from fastapi import HTTPException
import gspread

import sys
import os

# 添加父目錄到路徑
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import config
from modules import firebase, sheets, cache, utils, booking
from modules.models import (
    BookPayload, QueryPayload, ModifyPayload, DeletePayload,
    CheckInPayload, MailPayload
)

logger = logging.getLogger("shuttle-api.booking")


def handle_ops_request(action: str, data: Dict[str, Any]) -> Dict[str, Any]:
    """處理預約操作請求"""
    action = (action or "").strip().lower()
    logger.info(f"OPS action={action} payload={data}")
    
    try:
        # ===== 查詢（使用快取，不需要開啟主表 Worksheet） =====
        if action == "query":
            p = QueryPayload(**data)
            if not (p.booking_id or p.phone or p.email):
                raise HTTPException(400, "至少提供 booking_id / phone / email 其中一項")
            
            # 使用快取機制，減少 Google Sheets API 調用
            all_values, hmap = sheets.get_main_sheet_data()
            if not all_values:
                return []
            
            def get(row: List[str], key: str) -> str:
                return row[hmap[key] - 1] if key in hmap and len(row) >= hmap[key] else ""
            
            now = datetime.now()
            one_month_ago = now - timedelta(days=31)
            results: List[Dict[str, str]] = []
            
            for row in all_values[config.HEADER_ROW_MAIN:]:
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
                                time_hm = utils.time_hm_from_any(parts[1])
                        else:
                            date_iso = ""
                    except Exception:
                        # fallback to legacy columns
                        date_iso = get(row, "日期")
                        time_hm = utils.time_hm_from_any(get(row, "班次"))
                else:
                    date_iso = get(row, "日期")
                    time_hm = utils.time_hm_from_any(get(row, "班次"))
                
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
                # 信箱查詢使用大小寫不敏感比較
                if p.email:
                    row_email = get(row, "信箱").strip().lower()
                    query_email = p.email.strip().lower()
                    if query_email != row_email:
                        continue
                
                rec = {k: get(row, k) for k in hmap}
                # override date/time fields with values derived from 車次-日期時間
                if date_iso:
                    rec["日期"] = date_iso
                if time_hm:
                    rec["班次"] = time_hm
                    # update 車次欄以新的顯示格式
                    rec["車次"] = utils.display_trip_str(date_iso, time_hm)
                # 如果櫃檯審核為 n 則將預約狀態標為「已拒絕」
                if rec.get("櫃台審核", "").lower() == "n":
                    rec["預約狀態"] = "已拒絕"
                results.append(rec)
            
            logger.info(f"query results count={len(results)}")
            return results
        
        # 需要寫入操作，打開工作表
        ws_main = sheets.open_worksheet(config.SHEET_NAME_MAIN)
        all_values, hmap = sheets.get_main_sheet_data()
        headers = sheets.get_sheet_headers(ws_main, config.HEADER_ROW_MAIN)
        
        def setv(row_arr: List[str], col: str, v: Any):
            if col in hmap and 1 <= hmap[col] <= len(row_arr):
                if isinstance(v, (int, float)):
                    row_arr[hmap[col] - 1] = v
                elif isinstance(v, str):
                    row_arr[hmap[col] - 1] = v
                else:
                    row_arr[hmap[col] - 1] = str(v)
        
        row_cache: Dict[int, List[str]] = {}
        
        def _get_row_values(rowno: int) -> List[str]:
            if rowno not in row_cache:
                try:
                    row_cache[rowno] = ws_main.row_values(rowno) or []
                except Exception:
                    row_cache[rowno] = []
            return row_cache[rowno]
        
        def get_by_rowno(rowno: int, key: str) -> str:
            if key not in hmap:
                return ""
            row = _get_row_values(rowno)
            idx = hmap[key] - 1
            if idx < 0 or idx >= len(row):
                return ""
            return row[idx] or ""
        
        # ===== 新增預約 =====
        if action == "book":
            p = BookPayload(**data)
            
            # 先拿班次時間
            time_hm = utils.time_hm_from_any(p.time)
            
            # 容量檢查（可預約班次表是權威：可預約人數 = 現存剩餘數）
            station_for_cap = utils.normalize_station_for_capacity(
                p.direction, p.pickLocation, p.dropLocation
            )
            lock_id = booking.lock_id_for_capacity(p.date, time_hm)
            lock_holder = booking.acquire_capacity_lock(lock_id, p.date, time_hm)
            if not lock_holder:
                raise HTTPException(503, "系統繁忙，請稍後再試")
            
            rem = None
            wrote = False
            defer_release = False
            try:
                rem = booking.lookup_capacity(p.direction, p.date, time_hm, station_for_cap)
                if int(p.passengers) > int(rem):
                    raise HTTPException(409, f"capacity_exceeded:{p.passengers}>{rem}")
                
                # 產生預約編號：以「今日日期」為準
                today_iso = utils.today_iso_taipei()
                try:
                    booking_id = booking.generate_booking_id(today_iso)
                except Exception as e:
                    logger.warning(f"[booking_id] rtdb_failed type={type(e).__name__} msg={e}")
                    raise HTTPException(503, "暫時無法產生預約編號，請稍後再試")
                
                # QR 內容
                em6 = booking.email_hash6(p.email)
                qr_content = f"FT:{booking_id}:{em6}"
                qr_url = f"{config.BASE_URL}/api/qr/{urllib.parse.quote(qr_content)}"
                
                # 用 booking 模組統一產生 row
                p_dict = p.dict()
                newrow = booking.prepare_booking_row(
                    p_dict, booking_id, qr_content, headers, hmap
                )
                
                # 寫入 Google Sheet（關鍵操作）
                ws_main.append_row(newrow, value_input_option="USER_ENTERED")
                wrote = True
                logger.info(f"book appended booking_id={booking_id}")
                # 清除快取，確保下次讀取時獲取最新資料
                cache.invalidate_main_cache()
                expected_max = max(0, int(rem) - int(p.passengers))
                # 回應前先啟動背景等待與解鎖，避免前端等待過久
                defer_release = True
                threading.Thread(
                    target=booking.finalize_capacity_lock,
                    args=(lock_id, lock_holder, p.direction, p.date, time_hm, station_for_cap, expected_max),
                    daemon=True,
                ).start()
            finally:
                if not defer_release:
                    booking.release_capacity_lock(lock_id, lock_holder)
            
            # 立即回覆前端
            response_data = {
                "status": "success",
                "bookingId": booking_id,
                "qrUrl": qr_url,
                "qrContent": qr_content,
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
            booking.async_process_mail("book", booking_id, booking_info, qr_content, p.lang)
            
            return response_data
        
        # ===== 修改 =====
        elif action == "modify":
            p = ModifyPayload(**data)
            
            # 找到目標列
            rownos = booking.find_rows_by_predicate(
                all_values,
                headers,
                config.HEADER_ROW_MAIN - 1,
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
                old_time = utils.time_hm_from_any(parts[1] if len(parts) > 1 else parts[0])
            else:
                old_time = utils.time_hm_from_any(get_by_rowno(rowno, "班次"))
            
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
            new_time = utils.time_hm_from_any(p.time or old_time)
            new_pick = p.pickLocation or old_pick
            new_drop = p.dropLocation or old_drop
            new_pax = int(p.passengers if p.passengers is not None else old_pax)
            
            # 容量檢查
            station_for_cap_new = utils.normalize_station_for_capacity(new_dir, new_pick, new_drop)
            
            # 如果還是同一班次，只需檢查增加的差額
            same_trip = (
                new_dir,
                new_date,
                new_time,
                utils.normalize_station_for_capacity(old_dir, old_pick, old_drop),
            ) == (
                old_dir,
                old_date,
                utils.time_hm_from_any(old_time),
                utils.normalize_station_for_capacity(old_dir, old_pick, old_drop),
            )
            
            consume = 0
            if same_trip:
                delta = new_pax - old_pax
                consume = delta if delta > 0 else 0
            else:
                consume = new_pax
            
            lock_holder = None
            lock_id = None
            rem = None
            wrote = False
            defer_release = False
            if consume > 0:
                lock_id = booking.lock_id_for_capacity(new_date, new_time)
                lock_holder = booking.acquire_capacity_lock(lock_id, new_date, new_time)
                if not lock_holder:
                    raise HTTPException(503, "系統繁忙，請稍後再試")
            
            try:
                if consume > 0:
                    rem = booking.lookup_capacity(new_dir, new_date, new_time, station_for_cap_new)
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
                car_display = utils.display_trip_str(new_date, time_hm) if (new_date and time_hm) else None
                
                # 更新 unified 車次-日期時間 + 主班次時間
                if new_date and new_time:
                    date_obj = datetime.strptime(new_date, "%Y-%m-%d")
                    car_datetime = date_obj.strftime("%Y/%m/%d") + " " + new_time
                    updates["車次-日期時間"] = car_datetime
                    
                    main_departure = utils.compute_main_departure_datetime(
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
                    pk_idx, dp_idx, seg_str = utils.compute_indices_and_segments(new_pick, new_drop)
                
                updates["預約狀態"] = config.BOOKED_TEXT
                updates["預約人數"] = str(new_pax)
                
                # 備註增加一條「已修改」
                if "備註" in hmap:
                    current_note = ws_main.cell(rowno, hmap["備註"]).value or ""
                    new_note = f"{utils.tz_now_str()} 已修改"
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
                    em6 = booking.email_hash6(final_email)
                    qr_content = f"FT:{p.booking_id}:{em6}"
                    updates["QRCode編碼"] = qr_content
                
                if pk_idx is not None:
                    updates["上車索引"] = str(pk_idx)
                if dp_idx is not None:
                    updates["下車索引"] = str(dp_idx)
                if seg_str is not None:
                    updates["涉及路段範圍"] = seg_str
                
                if "最後操作時間" in hmap:
                    updates["最後操作時間"] = utils.tz_now_str() + " 已修改"
                
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
                    wrote = True
                
                logger.info(f"modify updated booking_id={p.booking_id}")
                # 清除快取，確保下次讀取時獲取最新資料
                cache.invalidate_main_cache()
                
                # 若影響容量，先回應前端，背景等待公式更新後釋放鎖
                if consume > 0 and rem is not None and wrote and lock_holder and lock_id:
                    expected_max = max(0, int(rem) - int(consume))
                    defer_release = True
                    threading.Thread(
                        target=booking.finalize_capacity_lock,
                        args=(lock_id, lock_holder, new_dir, new_date, new_time, station_for_cap_new, expected_max),
                        daemon=True,
                    ).start()
                
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
                    "qr_url": f"{config.BASE_URL}/api/qr/{urllib.parse.quote(qr_content)}" if qr_content else "",
                }
                booking.async_process_mail("modify", p.booking_id, booking_info, qr_content, p.lang)
                return response_data
            finally:
                if not defer_release and lock_holder:
                    booking.release_capacity_lock(lock_id, lock_holder)
        
        # ===== 刪除（取消） =====
        elif action == "delete":
            p = DeletePayload(**data)
            rownos = booking.find_rows_by_predicate(
                all_values,
                headers,
                config.HEADER_ROW_MAIN - 1,
                lambda r: r.get("預約編號") == p.booking_id
            )
            if not rownos:
                raise HTTPException(404, "找不到此預約編號")
            rowno = rownos[0]
            
            updates: Dict[str, str] = {}
            if "預約狀態" in hmap:
                updates["預約狀態"] = config.CANCELLED_TEXT
            if "備註" in hmap:
                current_note = ws_main.cell(rowno, hmap["備註"]).value or ""
                new_note = f"{utils.tz_now_str()} 已取消"
                updates["備註"] = f"{current_note}; {new_note}" if current_note else new_note
            if "最後操作時間" in hmap:
                updates["最後操作時間"] = utils.tz_now_str() + " 已刪除"
            
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
            logger.info(f"delete updated booking_id={p.booking_id}")
            # 清除快取，確保下次讀取時獲取最新資料
            cache.invalidate_main_cache()
            
            # 立即回覆前端
            response_data = {"status": "success", "booking_id": p.booking_id}
            
            # 非同步處理寄信（取消不需要車票）
            booking_info = {
                "booking_id": p.booking_id,
                "date": get_by_rowno(rowno, "日期"),
                "time": utils.time_hm_from_any(get_by_rowno(rowno, "班次")),
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
            booking.async_process_mail("cancel", p.booking_id, booking_info, None, p.lang)
            
            return response_data
        
        # ===== 掃碼上車 =====
        elif action == "check_in":
            p = CheckInPayload(**data)
            if not (p.code or p.booking_id):
                raise HTTPException(400, "需提供 code 或 booking_id")
            
            rownos = booking.find_rows_by_predicate(
                all_values,
                headers,
                config.HEADER_ROW_MAIN - 1,
                lambda r: r.get("QRCode編碼") == p.code or r.get("預約編號") == p.booking_id,
            )
            if not rownos:
                raise HTTPException(404, "找不到符合條件之訂單")
            rowno = rownos[0]
            
            updates: Dict[str, str] = {}
            if "乘車狀態" in hmap:
                updates["乘車狀態"] = "已上車"
            if "最後操作時間" in hmap:
                updates["最後操作時間"] = utils.tz_now_str() + " 已上車"
            
            batch_updates = []
            for col_name, value in updates.items():
                if col_name in hmap:
                    batch_updates.append({
                        'range': gspread.utils.rowcol_to_a1(rowno, hmap[col_name]),
                        'values': [[value]]
                    })
            if batch_updates:
                ws_main.batch_update(batch_updates, value_input_option="USER_ENTERED")
            logger.info(f"check_in row={rowno}")
            # 清除快取，確保下次讀取時獲取最新資料
            cache.invalidate_main_cache()
            return {"status": "success", "row": rowno}
        
        # ===== 寄信（手動補寄） =====
        elif action == "mail":
            p = MailPayload(**data)
            rownos = booking.find_rows_by_predicate(
                all_values,
                headers,
                config.HEADER_ROW_MAIN - 1,
                lambda r: r.get("預約編號") == p.booking_id
            )
            if not rownos:
                raise HTTPException(404, "找不到此預約編號")
            rowno = rownos[0]
            
            get = lambda k: get_by_rowno(rowno, k)
            info = {
                "booking_id": get("預約編號"),
                "date": get("日期"),
                "time": utils.time_hm_from_any(get("班次")),
                "direction": get("往返"),
                "pick": get("上車地點"),
                "drop": get("下車地點"),
                "name": get("姓名"),
                "phone": get("手機"),
                "email": get("信箱"),
                "pax": (get("確認人數") or get("預約人數") or "1"),
            }
            
            # 使用純文字郵件內容
            subject, text_body = booking.compose_mail_text(info, p.lang, p.kind)
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
                booking.send_email(
                    info["email"],
                    subject,
                    text_body,
                    attachment=attachment_bytes,
                    attachment_filename=f"shuttle_ticket_{info['booking_id']}.png" if attachment_bytes else None
                )
                status_text = f"{utils.tz_now_str()} 寄信成功"
            except Exception as e:
                status_text = f"{utils.tz_now_str()} 寄信失敗: {str(e)}"
            
            if "寄信狀態" in hmap:
                ws_main.update_acell(gspread.utils.rowcol_to_a1(rowno, hmap["寄信狀態"]), status_text)
            logger.info(f"manual mail result: {status_text}")
            return {
                "status": "success" if "成功" in status_text else "mail_failed",
                "booking_id": p.booking_id,
                "mail_note": status_text
            }
        else:
            raise HTTPException(400, f"未知 action：{action}")
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("server error")
        raise HTTPException(500, f"伺服器錯誤: {str(e)}")

