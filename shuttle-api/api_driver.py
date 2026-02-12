"""
司機端 API 實現
完整的 driver-api2 功能遷移
"""
import logging
import os
import time
import urllib.parse
import urllib.request
import json
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from fastapi import HTTPException, Query
import gspread

import sys
import os

# 添加父目錄到路徑
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import config
from modules import firebase, sheets, cache, utils, driver
from modules.driver_models import (
    DriverLocation, DriverCheckinRequest, DriverCheckinResponse,
    BookingIdRequest, TripStatusRequest, QrInfoRequest, QrInfoResponse,
    GoogleTripStartRequest, GoogleTripStartResponse, GoogleTripCompleteRequest,
    SystemStatusRequest, UpdateStationRequest, DriverAllData
)

logger = logging.getLogger("shuttle-api.driver")


# ========== GPS 定位功能 ==========
def handle_update_driver_location(loc: DriverLocation) -> Dict[str, Any]:
    """處理司機位置更新"""
    try:
        driver.update_driver_location(loc.lat, loc.lng, loc.timestamp, loc.trip_id)
        return {"status": "ok", "received": loc.dict()}
    except Exception as e:
        logger.error(f"Error updating driver location: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


def handle_get_driver_location() -> Dict[str, Any]:
    """獲取司機最新位置"""
    try:
        if not firebase.init_firebase():
            return {"lat": 0, "lng": 0, "timestamp": 0, "status": "firebase_not_initialized"}
        
        location_data = firebase.get_value("/driver_location")
        if location_data:
            return location_data
        else:
            return {"lat": 0, "lng": 0, "timestamp": 0, "status": "no_data_in_firebase"}
    except Exception as e:
        return {
            "lat": 0, "lng": 0, "timestamp": 0,
            "status": "error",
            "error_detail": str(e),
            "hint": "Check Cloud Run logs or FIREBASE_RTDB_URL env var."
        }


# ========== 司機數據 API ==========
def handle_driver_get_all_data() -> DriverAllData:
    """整合端點：一次返回 trips / trip_passengers / passenger_list"""
    try:
        values, hmap = sheets.get_main_sheet_data()
        trips, trip_passengers, passenger_list = driver.build_all_driver_data_optimized(values, hmap)
        
        # 轉換為 Pydantic 模型
        from modules.driver_models import DriverTrip, DriverPassenger, DriverAllPassenger
        
        trips_models = [DriverTrip(**t) for t in trips]
        trip_passengers_models = [DriverPassenger(**p) for p in trip_passengers]
        passenger_list_models = [DriverAllPassenger(**p) for p in passenger_list]
        
        return DriverAllData(
            trips=trips_models,
            trip_passengers=trip_passengers_models,
            passenger_list=passenger_list_models,
        )
    except Exception as e:
        logger.error(f"Error getting driver all data: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


def handle_driver_get_trips() -> List[dict]:
    """班次列表"""
    try:
        values, hmap = sheets.get_main_sheet_data()
        trips = driver.build_driver_trips(values, hmap)
        return trips
    except Exception as e:
        logger.error(f"Error getting driver trips: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


def handle_driver_get_trip_passengers(trip_id: str) -> List[dict]:
    """指定班次乘客列表"""
    try:
        values, hmap = sheets.get_main_sheet_data()
        passengers = driver.build_driver_trip_passengers(values, hmap, trip_id)
        return passengers
    except Exception as e:
        logger.error(f"Error getting trip passengers: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


def handle_driver_get_passenger_list() -> List[dict]:
    """乘客清單（出車總覽）"""
    try:
        values, hmap = sheets.get_main_sheet_data()
        passengers = driver.build_driver_all_passengers(values, hmap)
        return passengers
    except Exception as e:
        logger.error(f"Error getting passenger list: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# ========== QR Code 核銷 ==========
def handle_driver_checkin(req: DriverCheckinRequest) -> DriverCheckinResponse:
    """掃描 QRCode 後，將該訂單標記為「已上車」"""
    code = (req.qrcode or "").strip()
    if not code:
        raise HTTPException(400, "缺少 qrcode")
    
    parts = code.split(":")
    if len(parts) < 3 or parts[0] != "FT":
        return DriverCheckinResponse(
            status="error",
            message="QRCode 格式錯誤",
        )
    
    booking_id = parts[1].strip() if len(parts) >= 2 else ""
    
    # 不使用快取，每次讀取最新資料
    ws = sheets.open_worksheet(config.SHEET_NAME_MAIN)
    all_values, hmap = sheets.get_main_sheet_data()
    
    if "QRCode編碼" not in hmap:
        raise HTTPException(500, "主表缺少『QRCode編碼』欄位")
    
    # 用「QRCode編碼」來找列
    rowno = driver.find_qrcode_row(all_values, hmap, code)
    
    if rowno is None:
        return DriverCheckinResponse(
            status="not_found",
            message="找不到對應的預約（QRCode編碼）",
        )
    
    # 直接從 values 取值
    row_idx = rowno - 1
    row = all_values[row_idx] if 0 <= row_idx < len(all_values) else []
    
    def getv(col_name: str) -> str:
        ci = hmap.get(col_name, 0) - 1
        if ci < 0 or ci >= len(row):
            return ""
        return (row[ci] or "").strip()
    
    sheet_booking_id = getv("預約編號").strip()
    if sheet_booking_id:
        booking_id = sheet_booking_id
    
    main_raw = getv("主班次時間").strip()
    if not main_raw:
        return DriverCheckinResponse(
            status="error",
            message="此預約缺少『主班次時間』，無法核銷上車",
            booking_id=booking_id or None,
        )
    
    main_dt = driver.parse_main_dt(main_raw)
    if not main_dt:
        logger.warning(f"api_driver_checkin: 無法解析主班次時間: {main_raw}, booking_id: {booking_id}")
        return DriverCheckinResponse(
            status="error",
            message=f"主班次時間格式錯誤：{main_raw}",
            booking_id=booking_id or None,
        )
    
    ride_status_current = getv("乘車狀態").strip()
    if ride_status_current and ("已上車" in ride_status_current):
        pax_str = getv("確認人數") or getv("預約人數") or "1"
        pax = utils.safe_int(pax_str, 1)
        return DriverCheckinResponse(
            status="already_checked_in",
            message="此乘客已上車，不重複核銷",
            booking_id=booking_id or None,
            name=getv("姓名") or None,
            pax=pax,
            station=getv("上車地點") or None,
            main_datetime=main_dt.strftime("%Y/%m/%d %H:%M"),
        )
    
    now = utils.tz_now()
    diff_sec = (now - main_dt).total_seconds()
    
    limit_before = 30 * 60  # 30 分鐘前
    limit_after = 60 * 60   # 60 分鐘後
    
    # 太晚：逾期
    if diff_sec > limit_after:
        pax_str = getv("確認人數") or getv("預約人數") or "1"
        pax = utils.safe_int(pax_str, 1)
        return DriverCheckinResponse(
            status="expired",
            message="此班次已逾期，無法核銷上車",
            booking_id=booking_id or None,
            name=getv("姓名") or None,
            pax=pax,
            station=getv("上車地點") or None,
            main_datetime=main_dt.strftime("%Y/%m/%d %H:%M"),
        )
    
    # 太早：尚未發車
    if diff_sec < -limit_before:
        dt_str = main_dt.strftime("%Y/%m/%d %H:%M")
        pax_str = getv("確認人數") or getv("預約人數") or "1"
        pax = utils.safe_int(pax_str, 1)
        return DriverCheckinResponse(
            status="not_started",
            message=f"{dt_str} 班次，尚未發車",
            booking_id=booking_id or None,
            name=getv("姓名") or None,
            pax=pax,
            station=getv("上車地點") or None,
            main_datetime=dt_str,
        )
    
    # OK：在允許時間範圍內，允許核銷
    updates: Dict[str, str] = {}
    if "乘車狀態" in hmap:
        updates["乘車狀態"] = "已上車"
    if "最後操作時間" in hmap:
        updates["最後操作時間"] = utils.tz_now_str() + " 已上車(司機)"
    
    if updates:
        data = []
        for col_name, val in updates.items():
            ci = hmap[col_name]
            data.append({
                "range": gspread.utils.rowcol_to_a1(rowno, ci),
                "values": [[val]],
            })
        ws.batch_update(data, value_input_option="USER_ENTERED")
    
    # 清除快取
    cache.invalidate_main_cache()
    
    # 回傳給前端顯示
    pax_str = getv("確認人數") or getv("預約人數") or "1"
    pax = utils.safe_int(pax_str, 1)
    
    return DriverCheckinResponse(
        status="success",
        message="已完成上車紀錄",
        booking_id=booking_id or None,
        name=getv("姓名") or None,
        pax=pax,
        station=getv("上車地點") or None,
        main_datetime=main_dt.strftime("%Y/%m/%d %H:%M"),
    )


def handle_driver_no_show(req: BookingIdRequest) -> Dict[str, str]:
    """標記 No-show"""
    try:
        all_values, hmap = sheets.get_main_sheet_data()
        ws = sheets.open_worksheet(config.SHEET_NAME_MAIN)
        target_rowno = driver.find_booking_row(all_values, hmap, req.booking_id)
        if not target_rowno:
            raise HTTPException(status_code=404, detail="找不到對應預約編號")
        
        data = []
        if "乘車狀態" in hmap:
            data.append({
                "range": gspread.utils.rowcol_to_a1(target_rowno, hmap["乘車狀態"]),
                "values": [["No-show"]]
            })
        if "最後操作時間" in hmap:
            data.append({
                "range": gspread.utils.rowcol_to_a1(target_rowno, hmap["最後操作時間"]),
                "values": [[utils.tz_now_str() + " No-show(司機)"]]
            })
        if data:
            ws.batch_update(data, value_input_option="USER_ENTERED")
        cache.invalidate_main_cache()
        return {"status": "success"}
    except Exception as e:
        logger.error(f"Error handling no show: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


def handle_driver_manual_boarding(req: BookingIdRequest) -> Dict[str, str]:
    """手動登車"""
    try:
        all_values, hmap = sheets.get_main_sheet_data()
        ws = sheets.open_worksheet(config.SHEET_NAME_MAIN)
        target_rowno = driver.find_booking_row(all_values, hmap, req.booking_id)
        if not target_rowno:
            raise HTTPException(status_code=404, detail="找不到對應預約編號")
        
        data = []
        if "乘車狀態" in hmap:
            data.append({
                "range": gspread.utils.rowcol_to_a1(target_rowno, hmap["乘車狀態"]),
                "values": [["已上車"]]
            })
        if "最後操作時間" in hmap:
            data.append({
                "range": gspread.utils.rowcol_to_a1(target_rowno, hmap["最後操作時間"]),
                "values": [[utils.tz_now_str() + " 人工驗票(司機)"]]
            })
        if data:
            ws.batch_update(data, value_input_option="USER_ENTERED")
        cache.invalidate_main_cache()
        return {"status": "success"}
    except Exception as e:
        logger.error(f"Error handling manual boarding: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


def handle_driver_trip_status(req: TripStatusRequest) -> Dict[str, str]:
    """更新班次狀態"""
    try:
        sheet_name = "車次管理(櫃台)"
        try:
            ws = sheets.open_worksheet(sheet_name)
        except Exception:
            ws = sheets.open_worksheet("車次管理(備品)")
        
        headers = ws.row_values(6)
        headers = [(h or "").strip() for h in headers]
        
        def hidx(name: str) -> int:
            try:
                return headers.index(name)
            except ValueError:
                return -1
        
        idx_date = hidx("日期")
        idx_time = hidx("時間")
        if idx_time < 0:
            idx_time = hidx("班次")
        idx_status = hidx("出車狀態")
        idx_last = hidx("最後更新")
        
        if min(idx_date, idx_time, idx_status, idx_last) < 0:
            raise HTTPException(status_code=400, detail="表頭缺少必要欄位")
        
        # 解析傳入主班次時間
        raw = req.main_datetime.strip()
        parts = raw.split(" ")
        if len(parts) < 2:
            raise HTTPException(status_code=400, detail="主班次時間格式錯誤")
        target_date, target_time = parts[0], parts[1]
        
        def norm_dates(d: str) -> list:
            d = d.strip()
            if "-" in d:
                y, m, day = d.split("-")
            else:
                y, m, day = d.split("/")
            m2 = str(m).zfill(2)
            d2 = str(day).zfill(2)
            return [f"{y}/{m2}/{d2}", f"{y}-{m2}-{d2}"]
        
        def norm_time(t: str) -> list:
            t = t.strip()
            parts = t.split(":")
            if len(parts) == 1:
                return [t]
            h = parts[0]
            mm = parts[1] if len(parts) > 1 else "00"
            ss = parts[2] if len(parts) > 2 else None
            h2 = str(h).zfill(2)
            res = [f"{h2}:{mm}", f"{int(h)}:{mm}"]
            if ss is not None:
                res.append(f"{h2}:{mm}:{ss}")
                res.append(f"{int(h)}:{mm}:{ss}")
            return res
        
        t_dates = norm_dates(target_date)
        t_times = norm_time(target_time)
        
        values = ws.get_all_values()
        target_rowno: Optional[int] = None
        for i in range(6, len(values)):
            row = values[i]
            d = (row[idx_date] if idx_date < len(row) else "").strip()
            t_raw = (row[idx_time] if idx_time < len(row) else "").strip()
            try:
                rp = t_raw.split(":")
                t_norm = f"{str(rp[0]).zfill(2)}:{rp[1]}" if len(rp) >= 2 else t_raw
            except Exception:
                t_norm = t_raw
            if (d in t_dates) and (t_raw in t_times or t_norm in t_times):
                target_rowno = i + 1
                break
        
        if not target_rowno:
            raise HTTPException(status_code=404, detail="找不到對應主班次時間")
        
        now_text = utils.tz_now().strftime("%Y/%m/%d %H:%M")
        data = [
            {"range": gspread.utils.rowcol_to_a1(target_rowno, idx_status + 1), "values": [[req.status]]},
            {"range": gspread.utils.rowcol_to_a1(target_rowno, idx_last + 1), "values": [[now_text]]},
        ]
        ws.batch_update(data, value_input_option="USER_ENTERED")
        return {"status": "success"}
    except Exception as e:
        logger.error(f"Error handling trip status: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


def handle_driver_qrcode_info(req: QrInfoRequest) -> QrInfoResponse:
    """獲取 QR Code 資訊"""
    try:
        all_values, hmap = sheets.get_main_sheet_data()
        rowno = driver.find_qrcode_row(all_values, hmap, req.qrcode)
        if not rowno:
            return QrInfoResponse(
                booking_id=None, name=None, main_datetime=None,
                ride_status=None, station_up=None, station_down=None
            )
        
        row = all_values[rowno - 1]
        
        def getv(col: str) -> str:
            ci = hmap.get(col, 0) - 1
            return (row[ci] if 0 <= ci < len(row) else "").strip()
        
        main_raw = getv("主班次時間")
        return QrInfoResponse(
            booking_id=getv("預約編號") or None,
            name=getv("姓名") or None,
            main_datetime=main_raw or None,
            ride_status=getv("乘車狀態") or None,
            station_up=getv("上車地點") or None,
            station_down=getv("下車地點") or None,
        )
    except Exception as e:
        logger.error(f"Error getting QR code info: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# ========== Google Trip API ==========
def handle_google_trip_start(req: GoogleTripStartRequest) -> GoogleTripStartResponse:
    """開始 Google 行程"""
    try:
        dt = driver.parse_main_dt(req.main_datetime)
        if not dt:
            raise HTTPException(status_code=400, detail="主班次時間格式錯誤")
        
        trip_id = dt.strftime("%Y/%m/%d %H:%M")
        
        # 更新 Sheet 的出車狀態
        ws2 = None
        target_rowno: Optional[int] = None
        try:
            try:
                ws2 = sheets.open_worksheet("車次管理(櫃台)")
            except Exception:
                ws2 = sheets.open_worksheet("車次管理(備品)")
            
            headers = ws2.row_values(6)
            headers = [(h or "").strip() for h in headers]
            
            def hidx(name: str) -> int:
                try:
                    return headers.index(name)
                except ValueError:
                    return -1
            
            idx_date = hidx("日期")
            idx_time = hidx("班次") if hidx("時間") < 0 else hidx("時間")
            idx_status = hidx("出車狀態")
            idx_last = hidx("最後更新")
            
            target_date = dt.strftime("%Y/%m/%d")
            alt_date = dt.strftime("%Y-%m-%d")
            t1 = dt.strftime("%H:%M")
            
            values = ws2.get_all_values()
            for i in range(6, len(values)):
                row = values[i]
                d = (row[idx_date] if idx_date >= 0 and idx_date < len(row) else "").strip()
                t_raw = (row[idx_time] if idx_time >= 0 and idx_time < len(row) else "").strip()
                try:
                    rp = t_raw.split(":")
                    t_norm = f"{str(rp[0]).zfill(2)}:{rp[1]}" if len(rp) >= 2 else t_raw
                except Exception:
                    t_norm = t_raw
                if (d in (target_date, alt_date)) and (t_raw in (t1,) or t_norm in (t1,)):
                    target_rowno = i + 1
                    break
            
            if target_rowno and idx_status >= 0 and idx_last >= 0:
                now_text = utils.tz_now().strftime("%Y/%m/%d %H:%M")
                update_data = [
                    {"range": gspread.utils.rowcol_to_a1(target_rowno, idx_status + 1), "values": [["已發車"]]},
                    {"range": gspread.utils.rowcol_to_a1(target_rowno, idx_last + 1), "values": [[now_text]]},
                ]
                ws2.batch_update(update_data, value_input_option="USER_ENTERED")
        except Exception:
            pass
        
        if req.driver_role == 'desk':
            return GoogleTripStartResponse(trip_id=trip_id, share_url=None, stops=None)
        
        # 檢查 GPS 系統開關
        try:
            ws_system = sheets.open_worksheet(config.SHEET_NAME_SYSTEM)
            e19 = (ws_system.acell("E19").value or "").strip().lower()
            enabled = e19 in ("true", "t", "yes", "1")
        except Exception:
            enabled = True
        
        if not enabled:
            return GoogleTripStartResponse(trip_id=trip_id, share_url=None, stops=None)
        
        # 處理站點和路線
        stops_names: List[str] = []
        if req.stops and len(req.stops) > 0:
            STATION_MAP = {
                "1. 福泰大飯店 (去)": "福泰大飯店 Forte Hotel",
                "2. 南港捷運站": "南港展覽館捷運站 Nangang Exhibition Center - MRT Exit 3",
                "3. 南港火車站": "南港火車站 Nangang Train Station",
                "4. LaLaport 購物中心": "LaLaport Shopping Park",
                "5. 福泰大飯店 (回)": "福泰大飯店(回) Forte Hotel (Back)",
            }
            for app_station in req.stops:
                mapped = STATION_MAP.get(app_station, app_station)
                if mapped:
                    stops_names.append(mapped)
        else:
            # 從 Sheet 讀取（向後兼容）
            STATIONS = [
                "福泰大飯店 Forte Hotel",
                "南港展覽館捷運站 Nangang Exhibition Center - MRT Exit 3",
                "南港火車站 Nangang Train Station",
                "LaLaport Shopping Park",
                "福泰大飯店(回) Forte Hotel (Back)",
            ]
            if target_rowno and ws2:
                headers = ws2.row_values(6)
                headers = [(h or "").strip() for h in headers]
                station_indices = []
                for s in STATIONS:
                    try:
                        idx = headers.index(s)
                    except ValueError:
                        idx = next((i for i, h in enumerate(headers) if s.split(" ")[0] in h), -1)
                    station_indices.append(idx)
                if target_rowno:
                    values = ws2.get_all_values()
                    row = values[target_rowno - 1]
                    for s, idx in zip(STATIONS, station_indices):
                        val = (row[idx] if idx >= 0 and idx < len(row) else "").strip().lower()
                        is_skip = val in ("true", "t", "yes", "1")
                        if not is_skip:
                            stops_names.append(s)
        
        # 站點座標
        stops: List[Dict[str, Any]] = []
        for name in stops_names:
            coord = config.STATION_COORDS.get(name)
            if coord:
                stops.append({"lat": coord["lat"], "lng": coord["lng"], "name": name})
        
        # 生成 Google Directions polyline
        polyline_obj: Dict[str, Any] = {}
        try:
            api_key = os.environ.get("GOOGLE_MAPS_API_KEY")
            if api_key and len(stops) >= 2:
                origin = f"{stops[0]['lat']},{stops[0]['lng']}"
                destination = f"{stops[-1]['lat']},{stops[-1]['lng']}"
                if len(stops) > 2:
                    wp = "|".join([f"{s['lat']},{s['lng']}" for s in stops[1:-1]])
                    url = f"https://maps.googleapis.com/maps/api/directions/json?origin={origin}&destination={destination}&waypoints={wp}&key={api_key}"
                else:
                    url = f"https://maps.googleapis.com/maps/api/directions/json?origin={origin}&destination={destination}&key={api_key}"
                
                with urllib.request.urlopen(url, timeout=10) as resp:
                    data = json.loads(resp.read().decode())
                    if data.get("status") == "OK" and data.get("routes"):
                        route = data["routes"][0]
                        polyline_obj = {
                            "polyline": route["overview_polyline"]["points"],
                            "bounds": route.get("bounds"),
                        }
        except Exception as e:
            logger.warning(f"Error generating polyline: {e}")
        
        # 更新 Firebase
        if firebase.init_firebase():
            now_ms = int(time.time() * 1000)
            firebase.set_value("/current_trip_id", trip_id)
            firebase.set_value("/current_trip_status", "active")
            firebase.set_value("/current_trip_datetime", req.main_datetime)
            firebase.set_value("/current_trip_start_time", now_ms)
            firebase.set_value("/current_trip_stations", {"stops": stops_names})
            firebase.set_value("/current_trip_completed_stops", [])
            if stops_names:
                firebase.set_value("/current_trip_station", stops_names[0])
            
            if polyline_obj:
                route_data = {
                    "path": [{"lat": s["lat"], "lng": s["lng"]} for s in stops],
                    "polyline": polyline_obj.get("polyline"),
                    "bounds": polyline_obj.get("bounds"),
                }
                firebase.set_value("/current_trip_route", route_data)
                firebase.set_value(f"/trip/{trip_id}/route", route_data)
        
        return GoogleTripStartResponse(
            trip_id=trip_id,
            share_url=None,
            stops=stops
        )
    except Exception as e:
        logger.error(f"Error starting Google trip: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


def handle_google_trip_complete(req: GoogleTripCompleteRequest) -> Dict[str, str]:
    """完成 Google 行程"""
    try:
        success = driver.auto_complete_trip(
            trip_id=req.trip_id,
            main_datetime=req.main_datetime or ""
        )
        if success:
            return {"status": "success"}
        else:
            raise HTTPException(status_code=500, detail="結束班次失敗")
    except Exception as e:
        logger.error(f"Error completing Google trip: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


def handle_driver_route(trip_id: str) -> Dict[str, Any]:
    """讀取 Firebase 中該班次的路線資料"""
    try:
        if not firebase.init_firebase():
            return {"stops": [], "polyline": None}
        
        data = firebase.get_value(f"/trip/{trip_id}/route")
        return data or {"stops": [], "polyline": None}
    except Exception as e:
        logger.error(f"Error getting route: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Route read error: {str(e)}")


def handle_driver_system_status() -> Dict[str, Any]:
    """讀取 GPS 系統總開關狀態"""
    try:
        if not firebase.init_firebase():
            return {"enabled": True, "message": "讀取失敗，預設啟用"}
        
        enabled = firebase.get_value("/gps_system_enabled")
        if enabled is None:
            enabled = True
        return {"enabled": bool(enabled), "message": "GPS系統總開關狀態"}
    except Exception:
        return {"enabled": True, "message": "讀取失敗，預設啟用"}


def handle_driver_set_system_status(req: SystemStatusRequest) -> Dict[str, Any]:
    """寫入 GPS 系統總開關狀態"""
    try:
        if not firebase.init_firebase():
            raise HTTPException(status_code=500, detail="Firebase not initialized")
        
        firebase.set_value("/gps_system_enabled", bool(req.enabled))
        return {
            "status": "success",
            "enabled": bool(req.enabled),
            "message": "GPS系統總開關狀態已更新"
        }
    except Exception as e:
        logger.error(f"Error setting system status: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"寫入失敗: {str(e)}")


def handle_driver_update_station(req: UpdateStationRequest) -> Dict[str, str]:
    """更新當前站點到 Firebase"""
    try:
        if not req.trip_id or not req.current_station:
            raise HTTPException(status_code=400, detail="缺少 trip_id 或 current_station")
        
        if not firebase.init_firebase():
            raise HTTPException(status_code=500, detail="Firebase not initialized")
        
        firebase.set_value("/current_trip_station", req.current_station)
        return {"status": "success"}
    except Exception as e:
        logger.error(f"Error updating station: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

