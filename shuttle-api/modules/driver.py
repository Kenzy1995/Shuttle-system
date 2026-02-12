"""
司機端管理模組
處理所有司機端相關功能：GPS 追蹤、行程管理、站點管理等
"""
import logging
import math
import time
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

from fastapi import HTTPException

import sys
import os

# 添加父目錄到路徑
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
from modules import firebase, sheets, cache, utils

logger = logging.getLogger("shuttle-api.driver")


# ========== 輔助函數 ==========
def _col_index(hmap: Dict[str, int], col_name: str) -> int:
    """獲取列索引（0-based）"""
    return hmap.get(col_name, 0) - 1 if col_name in hmap else -1


def _get_cell(row: List[str], idx: int) -> str:
    """安全獲取單元格值"""
    if idx < 0 or idx >= len(row):
        return ""
    return (row[idx] or "").strip()


def col_index(hmap: Dict[str, int], col_name: str) -> int:
    """獲取列索引（0-based）- 公開函數"""
    return _col_index(hmap, col_name)


def get_cell(row: List[str], idx: int) -> str:
    """安全獲取單元格值 - 公開函數"""
    return _get_cell(row, idx)


def _parse_main_dt(raw: str) -> Optional[datetime]:
    """解析主班次時間"""
    if not raw:
        return None
    raw = raw.strip()
    
    # 標準化時間格式
    pattern = r'^(\d{4})[/-](\d{1,2})[/-](\d{1,2})\s+(\d{1,2}):(\d{2})(?::(\d{2}))?$'
    import re
    match = re.match(pattern, raw)
    if match:
        year = match.group(1)
        month = match.group(2).zfill(2)
        day = match.group(3).zfill(2)
        hour = match.group(4).zfill(2)
        minute = match.group(5)
        second = match.group(6) if match.lastindex >= 6 and match.group(6) else None
        
        date_part = f"{year}/{month}/{day}"
        if second:
            raw = f"{date_part} {hour}:{minute}:{second}"
        else:
            raw = f"{date_part} {hour}:{minute}"
    
    # 嘗試解析
    for fmt in ("%Y/%m/%d %H:%M", "%Y-%m-%d %H:%M", "%Y/%m/%d %H:%M:%S", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(raw, fmt)
        except ValueError:
            continue
    
    return None


# 公開函數供外部調用
def parse_main_dt(raw: str) -> Optional[datetime]:
    """解析主班次時間 - 公開函數"""
    return _parse_main_dt(raw)


def _normalize_main_dt_format(main_raw: str) -> str:
    """正規化主班次時間格式"""
    if not main_raw:
        return main_raw
    
    import re
    pattern = r'^(\d{4})[/-](\d{1,2})[/-](\d{1,2})\s+(\d{1,2}):(\d{2})(?::(\d{2}))?$'
    match = re.match(pattern, main_raw.strip())
    
    if match:
        year, month, day, hour, minute, second = match.groups()
        normalized_hour = hour.zfill(2)
        normalized_month = month.zfill(2)
        normalized_day = day.zfill(2)
        
        if second:
            return f"{year}/{normalized_month}/{normalized_day} {normalized_hour}:{minute}:{second}"
        else:
            return f"{year}/{normalized_month}/{normalized_day} {normalized_hour}:{minute}"
    
    return main_raw


# ========== GPS 定位功能 ==========
def haversine_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """計算兩點之間的距離（公尺），使用 Haversine 公式"""
    R = 6371000  # 地球半徑（公尺）
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)
    
    a = math.sin(delta_phi / 2) ** 2 + \
        math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2) ** 2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    
    return R * c


def update_driver_location(lat: float, lng: float, timestamp: float, trip_id: Optional[str] = None):
    """更新司機位置到 Firebase"""
    if not firebase.init_firebase():
        logger.warning("Firebase not initialized, skipping location update")
        return
    
    try:
        location_data = {
            "lat": lat,
            "lng": lng,
            "timestamp": timestamp,
            "updated_at": utils.tz_now_str(),
        }
        if trip_id:
            location_data["trip_id"] = trip_id
        
        firebase.set_value("/driver_location", location_data)
        
        # 如果當前有行程，更新路線歷史
        if trip_id:
            current_trip_id = firebase.get_value("/current_trip_id")
            if current_trip_id == trip_id:
                path_history_ref = firebase.get_reference("/current_trip_path_history")
                current_history = path_history_ref.get() or []
                now_ts = int(time.time() * 1000)
                THIRTY_MINUTES_MS = 60 * 60 * 1000
                
                # 清理超過 60 分鐘的歷史點
                current_history = [
                    point for point in current_history
                    if point.get("timestamp", 0) > (now_ts - THIRTY_MINUTES_MS)
                ]
                
                # 檢查是否需要記錄（最小間隔 5 秒）
                should_record = True
                if len(current_history) > 0:
                    last_point = current_history[-1]
                    last_ts = last_point.get("timestamp", 0)
                    time_diff = now_ts - last_ts
                    MIN_INTERVAL_MS = 5 * 1000
                    if time_diff < MIN_INTERVAL_MS:
                        should_record = False
                
                if should_record:
                    new_point = {
                        "lat": lat,
                        "lng": lng,
                        "timestamp": timestamp,
                        "updated_at": utils.tz_now_str()
                    }
                    current_history.append(new_point)
                    
                    MAX_HISTORY_POINTS = 500
                    if len(current_history) > MAX_HISTORY_POINTS:
                        current_history = current_history[-MAX_HISTORY_POINTS:]
                    
                    path_history_ref.set(current_history)
                
                # 檢查站點到達
                try:
                    check_station_arrival(lat, lng, trip_id)
                except Exception as e:
                    logger.warning(f"check_station_arrival error: {e}")
                
                # 檢查是否需要自動結束行程
                try:
                    trip_status = firebase.get_value("/current_trip_status")
                    trip_start_time = firebase.get_value("/current_trip_start_time")
                    if trip_status == "active" and trip_start_time:
                        now_ms = int(time.time() * 1000)
                        elapsed_ms = now_ms - int(trip_start_time)
                        AUTO_SHUTDOWN_MS = 40 * 60 * 1000
                        
                        if elapsed_ms >= AUTO_SHUTDOWN_MS:
                            trip_datetime = firebase.get_value("/current_trip_datetime")
                            auto_complete_trip(
                                trip_id=trip_id,
                                main_datetime=trip_datetime or ""
                            )
                except Exception as e:
                    logger.warning(f"Auto complete trip check error: {e}")
    except Exception as e:
        logger.error(f"Error updating driver location: {e}", exc_info=True)


def check_station_arrival(lat: float, lng: float, trip_id: str):
    """檢查司機是否到達某個站點"""
    if not firebase.init_firebase():
        return
    
    try:
        # 讀取 Firebase 數據
        stations_info = firebase.get_value("/current_trip_stations", {})
        if not stations_info or "stops" not in stations_info:
            return
        
        actual_stops_names = stations_info.get("stops", [])
        if not actual_stops_names:
            return
        
        completed_stops = firebase.get_value("/current_trip_completed_stops", [])
        route_data = firebase.get_value("/current_trip_route", {})
        route_path = route_data.get("path", []) if route_data else []
        
        # 根據站點類型調整距離閾值
        def get_station_threshold(stop_name: str) -> float:
            if "飯店" in stop_name or "Hotel" in stop_name:
                return 60
            elif "捷運" in stop_name or "MRT" in stop_name:
                return 40
            elif "火車" in stop_name or "Train" in stop_name:
                return 40
            else:
                return 50
        
        for stop_name in actual_stops_names:
            if stop_name in completed_stops:
                continue
            
            stop_coord = config.STATION_COORDS.get(stop_name)
            if not stop_coord:
                continue
            
            stop_lat = stop_coord["lat"]
            stop_lng = stop_coord["lng"]
            
            distance = haversine_distance(lat, lng, stop_lat, stop_lng)
            threshold = get_station_threshold(stop_name)
            
            distance_check = distance < threshold
            
            # 路線索引判斷
            route_index_check = False
            if route_path and len(route_path) > 0:
                station_nearest_idx = 0
                station_best_dist = float('inf')
                for i, point in enumerate(route_path):
                    dx = point.get("lat", 0) - stop_lat
                    dy = point.get("lng", 0) - stop_lng
                    dist = dx * dx + dy * dy
                    if dist < station_best_dist:
                        station_best_dist = dist
                        station_nearest_idx = i
                
                driver_nearest_idx = 0
                driver_best_dist = float('inf')
                for i, point in enumerate(route_path):
                    dx = point.get("lat", 0) - lat
                    dy = point.get("lng", 0) - lng
                    dist = dx * dx + dy * dy
                    if dist < driver_best_dist:
                        driver_best_dist = dist
                        driver_nearest_idx = i
                
                if driver_nearest_idx > station_nearest_idx and distance < 100:
                    route_index_check = True
            
            if distance_check or route_index_check:
                if stop_name not in completed_stops:
                    completed_stops.append(stop_name)
                    firebase.set_value("/current_trip_completed_stops", completed_stops)
                    next_stop = get_next_station(actual_stops_names, completed_stops)
                    if next_stop:
                        firebase.set_value("/current_trip_station", next_stop)
                    else:
                        firebase.set_value("/current_trip_station", "所有站點已完成")
                break
    except Exception as e:
        logger.warning(f"check_station_arrival error: {e}", exc_info=True)


def get_next_station(stops: list, completed_stops: list) -> str:
    """根據已到達站點列表，返回下一個未到達的站點"""
    for stop in stops:
        stop_name = stop if isinstance(stop, str) else stop.get("name", "")
        if stop_name and stop_name not in completed_stops:
            return stop_name
    return ""


def auto_complete_trip(trip_id: str, main_datetime: str) -> bool:
    """自動結束行程"""
    try:
        if not firebase.init_firebase():
            return False
        
        # 更新狀態為已結束
        firebase.set_value("/current_trip_status", "ended")
        if main_datetime:
            firebase.set_value("/last_trip_datetime", main_datetime)
        
        # 清除當前行程標記
        firebase.set_value("/current_trip_id", "")
        firebase.set_value("/current_trip_route", {})
        firebase.set_value("/current_trip_datetime", "")
        firebase.set_value("/current_trip_stations", {})
        firebase.set_value("/current_trip_station", "")
        firebase.set_value("/current_trip_path_history", [])
        firebase.set_value("/current_trip_completed_stops", [])
        
        # 刪除歷史路線
        if trip_id:
            try:
                firebase.delete_path(f"/trip/{trip_id}/route")
            except Exception:
                pass
        
        logger.info(f"Auto completed trip: {trip_id}")
        return True
    except Exception as e:
        logger.error(f"Error auto completing trip: {e}", exc_info=True)
        return False


# ========== 站點映射常數 ==========
STATION_NAMES = {
    "hotel": "福泰大飯店 Forte Hotel",
    "mrt": "南港展覽館捷運站 Nangang Exhibition Center - MRT Exit 3",
    "train": "南港火車站 Nangang Train Station",
    "mall": "LaLaport Shopping Park"
}

SORT_GO_MAP = {
    "福泰大飯店 Forte Hotel": 1,
    "南港展覽館捷運站 Nangang Exhibition Center - MRT Exit 3": 2,
    "南港火車站 Nangang Train Station": 3,
    "LaLaport Shopping Park": 4
}

SORT_BACK_MAP = {
    "南港展覽館捷運站 Nangang Exhibition Center - MRT Exit 3": 1,
    "南港火車站 Nangang Train Station": 2,
    "LaLaport Shopping Park": 3
}

DROPOFF_GO_MAP = {
    "南港展覽館捷運站 Nangang Exhibition Center - MRT Exit 3": 1,
    "南港火車站 Nangang Train Station": 2,
    "LaLaport Shopping Park": 3
}

DROPOFF_BACK_MAP = {
    "LaLaport Shopping Park": 1,
    "南港火車站 Nangang Train Station": 2,
    "南港展覽館捷運站 Nangang Exhibition Center - MRT Exit 3": 3
}


# ========== 數據處理函數 ==========
def find_qrcode_row(values: List[List[str]], hmap: Dict[str, int], qrcode_value: str) -> Optional[int]:
    """在 values 中尋找 QRCode 對應的行號（1-based）"""
    col = hmap.get("QRCode編碼")
    if not col:
        return None
    ci = col - 1
    
    for i, row in enumerate(values[config.HEADER_ROW_MAIN:], start=config.HEADER_ROW_MAIN + 1):
        if ci < len(row) and (row[ci] or "").strip() == qrcode_value:
            return i
    return None


def find_booking_row(values: List[List[str]], hmap: Dict[str, int], booking_id: str) -> Optional[int]:
    """在 values 中尋找 booking_id 對應的行號（1-based）"""
    idx_booking = _col_index(hmap, "預約編號")
    if idx_booking < 0:
        return None
    for i, row in enumerate(values[config.HEADER_ROW_MAIN:], start=config.HEADER_ROW_MAIN + 1):
        if idx_booking < len(row) and (row[idx_booking] or "").strip() == booking_id:
            return i
    return None


# ========== 數據構建函數（從 driver-api2 遷移）==========
def build_all_driver_data_optimized(
    values: List[List[str]],
    hmap: Dict[str, int],
) -> Tuple[List[dict], List[dict], List[dict]]:
    """
    優化版：在一次遍歷中同時構建 trips、trip_passengers 和 all_passengers
    減少數據遍歷次數，提高性能
    """
    # 預先計算所有需要的列索引
    idx_main_dt = _col_index(hmap, "主班次時間")
    if idx_main_dt < 0:
        return [], [], []
    
    idx_booking = _col_index(hmap, "預約編號")
    idx_name = _col_index(hmap, "姓名")
    idx_phone = _col_index(hmap, "手機")
    idx_room = _col_index(hmap, "房號")
    idx_pick = _col_index(hmap, "上車地點")
    idx_drop = _col_index(hmap, "下車地點")
    idx_status = _col_index(hmap, "乘車狀態")
    idx_dir = _col_index(hmap, "往返")
    idx_qr = _col_index(hmap, "QRCode編碼")
    idx_confirm_status = _col_index(hmap, "確認狀態")
    idx_rid = _col_index(hmap, "預約編號")
    idx_car_raw = _col_index(hmap, "車次")
    idx_ride = _col_index(hmap, "乘車狀態")
    
    pax_col = hmap.get("確認人數", hmap.get("預約人數", 0))
    idx_pax = pax_col - 1 if pax_col else -1
    status_col = hmap.get("確認狀態")
    idx_status_check = status_col - 1 if status_col else -1
    
    # 站點文字常數（使用模組級常數）
    hotel = STATION_NAMES.get("hotel", "福泰大飯店 Forte Hotel")
    mrt = STATION_NAMES.get("mrt", "南港展覽館捷運站 Nangang Exhibition Center - MRT Exit 3")
    train = STATION_NAMES.get("train", "南港火車站 Nangang Train Station")
    mall = STATION_NAMES.get("mall", "LaLaport Shopping Park")
    
    now = utils.tz_now()
    cutoff = now - timedelta(hours=1)
    
    # 結果容器
    trips_by_dt: Dict[str, dict] = {}
    trip_passengers_list: List[dict] = []
    all_passengers_base: List[Dict[str, Any]] = []
    
    # 單次遍歷處理所有數據
    for row in values[config.HEADER_ROW_MAIN:]:
        if not any(row):
            continue
        if idx_main_dt >= len(row):
            continue
        
        main_raw = _get_cell(row, idx_main_dt)
        if not main_raw:
            continue
        
        # 排除已取消
        if idx_status_check >= 0 and idx_status_check < len(row):
            st = _get_cell(row, idx_status_check)
            if "❌" in st or st == config.CANCELLED_TEXT:
                continue
        
        dt = _parse_main_dt(main_raw)
        if not dt:
            continue
        if dt < cutoff:
            continue
        
        # 正規化 trip_id
        normalized_trip_id = _normalize_main_dt_format(main_raw)
        date_str = dt.strftime("%Y-%m-%d")
        time_str = dt.strftime("%H:%M")
        
        # 構建 trips
        if normalized_trip_id not in trips_by_dt:
            trips_by_dt[normalized_trip_id] = {
                "trip_id": normalized_trip_id,
                "date": date_str,
                "time": time_str,
                "total_pax": 0,
            }
        
        if idx_pax >= 0 and idx_pax < len(row):
            trips_by_dt[normalized_trip_id]["total_pax"] += utils.safe_int(row[idx_pax], 0)
        
        # 構建 trip_passengers
        booking_id = _get_cell(row, idx_booking)
        name = _get_cell(row, idx_name)
        phone = _get_cell(row, idx_phone)
        room = _get_cell(row, idx_room) or "(餐客)"
        ride_status = _get_cell(row, idx_status)
        qrcode = _get_cell(row, idx_qr)
        direction = _get_cell(row, idx_dir)
        pick = _get_cell(row, idx_pick)
        drop = _get_cell(row, idx_drop)
        
        pax = 1
        if idx_pax >= 0 and idx_pax < len(row):
            pax = utils.safe_int(row[idx_pax], 1)
        
        if pick:
            trip_passengers_list.append({
                "trip_id": normalized_trip_id,
                "station": pick,
                "updown": "上車",
                "booking_id": booking_id,
                "name": name,
                "phone": phone,
                "room": room,
                "pax": pax,
                "status": ride_status,
                "direction": direction,
                "qrcode": qrcode,
            })
        
        if drop:
            trip_passengers_list.append({
                "trip_id": normalized_trip_id,
                "station": drop,
                "updown": "下車",
                "booking_id": booking_id,
                "name": name,
                "phone": phone,
                "room": room,
                "pax": pax,
                "status": ride_status,
                "direction": direction,
                "qrcode": qrcode,
            })
        
        # 構建 all_passengers 基礎數據
        rid = _get_cell(row, idx_rid)
        car_raw = _get_cell(row, idx_car_raw)
        phone_raw = _get_cell(row, idx_phone)
        room_raw = _get_cell(row, idx_room)
        qty_raw = _get_cell(row, idx_pax) if idx_pax >= 0 and idx_pax < len(row) else ""
        ride_status_all = _get_cell(row, idx_ride)
        
        phone_text = phone_raw if phone_raw else ""
        room_text = room_raw if room_raw else ""
        qty = utils.safe_int(qty_raw, 1)
        
        up = pick
        down = drop
        
        sort_go = SORT_GO_MAP.get(up, 99)
        if up in SORT_BACK_MAP:
            sort_back = SORT_BACK_MAP[up]
        elif down == hotel:
            sort_back = 4
        else:
            sort_back = 99
        
        station_sort = sort_go if direction == "去程" else sort_back
        
        hotel_go = "上" if (direction == "去程" and up == hotel) else ""
        
        if up == mrt or down == mrt:
            mrt_col = "上" if up == mrt else "下"
        else:
            mrt_col = ""
        
        if up == train or down == train:
            train_col = "上" if up == train else "下"
        else:
            train_col = ""
        
        if up == mall or down == mall:
            mall_col = "上" if up == mall else "下"
        else:
            mall_col = ""
        
        hotel_back = "下" if (direction == "回程" and down == hotel) else ""
        
        if direction == "去程":
            dropoff_order = DROPOFF_GO_MAP.get(down, 4)
        elif direction == "回程":
            dropoff_order = DROPOFF_BACK_MAP.get(up, 4)
        else:
            dropoff_order = 99
        
        all_passengers_base.append({
            "car_raw": car_raw,
            "main_dt_raw": main_raw,
            "main_dt": dt,
            "booking_id": rid,
            "ride_status": ride_status_all,
            "direction": direction,
            "station_sort": station_sort,
            "dropoff_order": dropoff_order,
            "name": name,
            "phone": phone_text,
            "room": room_text,
            "qty": qty,
            "hotel_go": hotel_go,
            "mrt": mrt_col,
            "train": train_col,
            "mall": mall_col,
            "hotel_back": hotel_back,
        })
    
    # 排序 trips
    trips = sorted(trips_by_dt.values(), key=lambda t: (t["date"], t["time"]))
    
    # 排序 trip_passengers
    def sort_key_passenger(p):
        return (p["station"], 0 if p["updown"] == "上車" else 1, p["booking_id"])
    trip_passengers = sorted(trip_passengers_list, key=sort_key_passenger)
    
    # 排序 all_passengers
    def sort_key_all(row):
        dir_val = row.get("direction", "")
        dir_rank = 0 if dir_val == "去程" else 1
        return (row["main_dt"], dir_rank, row["station_sort"], row["dropoff_order"])
    
    all_passengers_base.sort(key=sort_key_all)
    
    result_all: List[dict] = []
    for row in all_passengers_base:
        dt = row["main_dt"]
        depart_time = dt.strftime("%H:%M") if dt else ""
        normalized_main_dt = _normalize_main_dt_format(row["main_dt_raw"])
        result_all.append({
            "booking_id": row["booking_id"],
            "main_datetime": normalized_main_dt,
            "depart_time": depart_time,
            "name": row["name"],
            "phone": row["phone"],
            "room": row["room"],
            "pax": row["qty"],
            "ride_status": row["ride_status"],
            "direction": row["direction"],
            "hotel_go": row["hotel_go"],
            "mrt": row["mrt"],
            "train": row["train"],
            "mall": row["mall"],
            "hotel_back": row["hotel_back"],
        })
    
    return trips, trip_passengers, result_all


def build_driver_trips(values: List[List[str]], hmap: Dict[str, int]) -> List[dict]:
    """構建班次列表"""
    trips, _, _ = build_all_driver_data_optimized(values, hmap)
    return trips


def build_driver_trip_passengers(
    values: List[List[str]], hmap: Dict[str, int], trip_id: str
) -> List[dict]:
    """構建指定班次的乘客列表"""
    _, trip_passengers, _ = build_all_driver_data_optimized(values, hmap)
    return [p for p in trip_passengers if p["trip_id"] == trip_id]


def build_driver_all_passengers(values: List[List[str]], hmap: Dict[str, int]) -> List[dict]:
    """構建所有乘客列表"""
    _, _, passenger_list = build_all_driver_data_optimized(values, hmap)
    return passenger_list

