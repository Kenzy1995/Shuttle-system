"""
統一後端服務 - 主應用文件
整合 booking-api, booking-manager, driver-api2 的所有功能
"""
import logging
import sys
import os

from fastapi import FastAPI, HTTPException, Response, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Any, Dict, List, Optional

# 設置日誌
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s %(message)s"
)
logger = logging.getLogger("shuttle-api")

# 導入配置和模組
import config
from modules import firebase, sheets, cache, utils, booking, driver
from modules.models import OpsRequest
try:
    from modules.driver_models import (
        DriverLocation, DriverCheckinRequest, DriverCheckinResponse,
        BookingIdRequest, TripStatusRequest, QrInfoRequest, QrInfoResponse,
        GoogleTripStartRequest, GoogleTripStartResponse, GoogleTripCompleteRequest,
        SystemStatusRequest, UpdateStationRequest, DriverAllData
    )
except ImportError as e:
    logger.warning(f"Failed to import driver models: {e}")
    # 提供空模型以避免啟動錯誤
    from pydantic import BaseModel
    class DriverLocation(BaseModel): pass
    class DriverCheckinRequest(BaseModel): pass
    class DriverCheckinResponse(BaseModel): pass
    class BookingIdRequest(BaseModel): pass
    class TripStatusRequest(BaseModel): pass
    class QrInfoRequest(BaseModel): pass
    class QrInfoResponse(BaseModel): pass
    class GoogleTripStartRequest(BaseModel): pass
    class GoogleTripStartResponse(BaseModel): pass
    class GoogleTripCompleteRequest(BaseModel): pass
    class SystemStatusRequest(BaseModel): pass
    class UpdateStationRequest(BaseModel): pass
    class DriverAllData(BaseModel): pass
from api_booking import handle_ops_request
try:
    from api_driver import (
        handle_update_driver_location, handle_get_driver_location,
        handle_driver_get_all_data, handle_driver_get_trips,
        handle_driver_get_trip_passengers, handle_driver_get_passenger_list,
        handle_driver_checkin, handle_driver_no_show, handle_driver_manual_boarding,
        handle_driver_trip_status, handle_driver_qrcode_info,
        handle_google_trip_start, handle_google_trip_complete,
        handle_driver_route, handle_driver_system_status,
        handle_driver_set_system_status, handle_driver_update_station
    )
except ImportError as e:
    logger.warning(f"Failed to import driver API handlers: {e}")
    # 提供空實現以避免啟動錯誤
    def handle_update_driver_location(*args, **kwargs):
        return {"status": "error", "message": "Driver API not available"}
    handle_get_driver_location = handle_update_driver_location
    handle_driver_get_all_data = handle_update_driver_location
    handle_driver_get_trips = handle_update_driver_location
    handle_driver_get_trip_passengers = handle_update_driver_location
    handle_driver_get_passenger_list = handle_update_driver_location
    handle_driver_checkin = handle_update_driver_location
    handle_driver_no_show = handle_update_driver_location
    handle_driver_manual_boarding = handle_update_driver_location
    handle_driver_trip_status = handle_update_driver_location
    handle_driver_qrcode_info = handle_update_driver_location
    handle_google_trip_start = handle_update_driver_location
    handle_google_trip_complete = handle_update_driver_location
    handle_driver_route = handle_update_driver_location
    handle_driver_system_status = handle_update_driver_location
    handle_driver_set_system_status = handle_update_driver_location
    handle_driver_update_station = handle_update_driver_location

# ========== FastAPI 應用初始化 ==========
app = FastAPI(
    title="Shuttle API",
    description="統一後端服務 - 整合預約、司機、班次管理功能",
    version="2.0.0"
)

# CORS 配置
app.add_middleware(
    CORSMiddleware,
    allow_origins=config.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ========== 應用啟動事件 ==========
@app.on_event("startup")
async def startup_event():
    """應用啟動時自動初始化 Firebase 路徑"""
    logger.info("Application startup: Ensuring Firebase paths exist")
    firebase.init_firebase()

# ========== 健康檢查端點 ==========
@app.get("/health")
def health():
    return {"status": "ok", "time": utils.tz_now_str()}

# ========== booking-api 功能遷移 ==========

# /api/sheet (從 booking-api/server.py 遷移)
@app.get("/api/sheet")
async def get_sheet_data(sheet: str = config.SHEET_NAME_CAP, range: Optional[str] = None):
    """
    Fetches rows from a Google Sheet via the Sheets API.
    Optional query parameters:
    - sheet: Name of the sheet tab to query. Defaults to `config.SHEET_NAME_CAP`.
    - range: A custom A1 notation range (e.g. 'A2:E10').
    """
    values, status_code = sheets.get_sheet_data_api(sheet, range)
    if status_code != 200:
        raise HTTPException(status_code=status_code, detail="Error fetching sheet data")
    
    import json
    return Response(
        content=json.dumps(values, ensure_ascii=False),
        media_type="application/json",
        status_code=200
    )

# /api/realtime/location (從 booking-api/server.py 遷移)
@app.get("/api/realtime/location")
def api_realtime_location():
    """
    讀取 Firebase 中的即時位置資料（原 booking-api /api/realtime/location）
    返回：GPS系統總開關、司機位置、當前班次信息、路線、站點等
    """
    try:
        if not firebase.init_firebase():
            raise HTTPException(status_code=500, detail="Firebase initialization failed")
        
        # 讀取 GPS 系統總開關（優先從 Sheet 的「系統」E19 讀取）
        gps_system_enabled = None
        try:
            values = sheets.get_sheet_data_via_api("系統", "系統!E19")
            if values and len(values) > 0 and len(values[0]) > 0:
                e19_value = (values[0][0] or "").strip().lower()
                gps_system_enabled = e19_value in ("true", "t", "yes", "1")
        except Exception:
            pass
        
        # 如果從 Sheet 讀取失敗，嘗試從 Firebase 讀取
        if gps_system_enabled is None:
            gps_system_enabled = firebase.get_value("/gps_system_enabled")
        
        # 如果都沒有，預設為 False（關閉）
        if gps_system_enabled is None:
            gps_system_enabled = False
        
        # 讀取司機位置
        driver_location = firebase.get_value("/driver_location") or {}
        
        # 讀取當前班次信息
        current_trip_id = firebase.get_value("/current_trip_id") or ""
        current_trip_status = firebase.get_value("/current_trip_status") or ""
        current_trip_datetime = firebase.get_value("/current_trip_datetime") or ""
        current_trip_route = firebase.get_value("/current_trip_route") or {}
        current_trip_stations = firebase.get_value("/current_trip_stations") or {}
        current_trip_station = firebase.get_value("/current_trip_station") or ""
        current_trip_start_time = firebase.get_value("/current_trip_start_time") or 0
        current_trip_completed_stops = firebase.get_value("/current_trip_completed_stops") or []
        last_trip_datetime = firebase.get_value("/last_trip_datetime") or ""
        
        # 自動結束檢查邏輯（從原 booking-api 遷移）
        import time
        if current_trip_status == "active" and current_trip_start_time:
            now_ms = int(time.time() * 1000)
            elapsed_ms = now_ms - int(current_trip_start_time)
            
            if elapsed_ms >= config.AUTO_SHUTDOWN_MS:
                # 自動結束班次
                try:
                    if current_trip_id:
                        firebase.delete_path(f"/trip/{current_trip_id}/route")
                except Exception:
                    pass
                
                firebase.set_value("/current_trip_status", "ended")
                if current_trip_datetime:
                    firebase.set_value("/last_trip_datetime", current_trip_datetime)
                firebase.set_value("/current_trip_id", "")
                firebase.set_value("/current_trip_route", {})
                firebase.set_value("/current_trip_datetime", "")
                firebase.set_value("/current_trip_stations", {})
                
                current_trip_status = "ended"
                if current_trip_datetime:
                    last_trip_datetime = current_trip_datetime
        
        # 獲取 GPS 位置歷史
        current_trip_path_history = []
        try:
            if current_trip_id:
                current_trip_path_history = firebase.get_value("/current_trip_path_history") or []
        except Exception:
            pass
        
        return {
            "gps_system_enabled": bool(gps_system_enabled),
            "driver_location": driver_location,
            "current_trip_id": current_trip_id,
            "current_trip_status": current_trip_status,
            "current_trip_datetime": current_trip_datetime,
            "current_trip_route": current_trip_route,
            "current_trip_stations": current_trip_stations,
            "current_trip_station": current_trip_station,
            "current_trip_start_time": int(current_trip_start_time) if current_trip_start_time else 0,
            "current_trip_completed_stops": current_trip_completed_stops,
            "current_trip_path_history": current_trip_path_history,
            "last_trip_datetime": last_trip_datetime
        }
        
    except Exception as e:
        logger.error(f"Error in /api/realtime/location: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

# ========== 預約管理 API（原 booking-manager）==========
@app.options("/api/ops")
@app.options("/api/ops/")
def ops_options():
    """CORS 預檢請求"""
    return Response(status_code=204)


@app.post("/api/ops")
@app.post("/api/ops/")
def ops(req: OpsRequest):
    """
    預約操作 API（原 booking-manager /api/ops）
    支持：book, modify, cancel, query, check_in, mail
    """
    return handle_ops_request(req.action, req.data)


@app.get("/api/qr/{code}")
def get_qr_code(code: str):
    """
    QR Code 生成 API（原 booking-manager /api/qr/{code}）
    返回 QR Code 圖片（PNG 格式）
    """
    try:
        import urllib.parse
        decoded_code = urllib.parse.unquote(code)
        qr_image_bytes = booking.generate_qr_code_image(decoded_code)
        return Response(content=qr_image_bytes, media_type="image/png")
    except Exception as e:
        logger.error(f"Error generating QR code: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"QR 生成失敗: {str(e)}")

# ========== 司機端 API（原 driver-api2）==========
@app.post("/api/driver/location")
def update_driver_location(loc: DriverLocation):
    """更新司機位置（原 driver-api2 /api/driver/location）"""
    return handle_update_driver_location(loc)


@app.get("/api/driver/location")
def get_driver_location():
    """獲取司機位置（原 driver-api2 /api/driver/location）"""
    return handle_get_driver_location()


@app.get("/api/driver/data", response_model=DriverAllData)
def driver_get_all_data():
    """整合端點：一次返回 trips / trip_passengers / passenger_list"""
    return handle_driver_get_all_data()


@app.get("/api/driver/trips")
def driver_get_trips():
    """班次列表"""
    return handle_driver_get_trips()


@app.get("/api/driver/trip_passengers")
def driver_get_trip_passengers(
    trip_id: str = Query(..., description="主班次時間原始字串，例如 2025/12/08 18:30")
):
    """指定班次乘客列表"""
    return handle_driver_get_trip_passengers(trip_id)


@app.get("/api/driver/passenger_list")
def driver_get_passenger_list():
    """乘客清單（出車總覽）"""
    return handle_driver_get_passenger_list()


@app.post("/api/driver/checkin", response_model=DriverCheckinResponse)
def driver_checkin(req: DriverCheckinRequest):
    """掃描 QRCode 後，將該訂單標記為「已上車」"""
    return handle_driver_checkin(req)


@app.post("/api/driver/no_show")
def driver_no_show(req: BookingIdRequest):
    """標記 No-show"""
    return handle_driver_no_show(req)


@app.post("/api/driver/manual_boarding")
def driver_manual_boarding(req: BookingIdRequest):
    """手動登車"""
    return handle_driver_manual_boarding(req)


@app.post("/api/driver/trip_status")
def driver_trip_status(req: TripStatusRequest):
    """更新班次狀態"""
    return handle_driver_trip_status(req)


@app.post("/api/driver/qrcode_info", response_model=QrInfoResponse)
def driver_qrcode_info(req: QrInfoRequest):
    """獲取 QR Code 資訊"""
    return handle_driver_qrcode_info(req)


@app.post("/api/driver/google/trip_start", response_model=GoogleTripStartResponse)
def driver_google_trip_start(req: GoogleTripStartRequest):
    """開始 Google 行程"""
    return handle_google_trip_start(req)


@app.post("/api/driver/google/trip_complete")
def driver_google_trip_complete(req: GoogleTripCompleteRequest):
    """完成 Google 行程"""
    return handle_google_trip_complete(req)


@app.get("/api/driver/route")
def driver_route(trip_id: str = Query(..., description="主班次時間，例如 2025/12/14 14:30")):
    """讀取 Firebase 中該班次的路線資料"""
    return handle_driver_route(trip_id)


@app.get("/api/driver/system_status")
def driver_system_status():
    """讀取 GPS 系統總開關狀態"""
    return handle_driver_system_status()


@app.post("/api/driver/system_status")
def driver_set_system_status(req: SystemStatusRequest):
    """寫入 GPS 系統總開關狀態"""
    return handle_driver_set_system_status(req)


@app.post("/api/driver/update_station")
def driver_update_station(req: UpdateStationRequest):
    """更新當前站點到 Firebase"""
    return handle_driver_update_station(req)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=config.PORT)
    CORSMiddleware,
    allow_origins=config.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ========== 啟動事件 ==========
@app.on_event("startup")
async def startup_event():
    """應用啟動時自動初始化 Firebase"""
    logger.info("Application startup: Initializing services...")
    firebase.init_firebase()
    logger.info("Application startup: Services initialized")


# ========== 健康檢查 ==========
@app.get("/health")
@app.get("/api/health")
def health():
    """健康檢查端點"""
    return {
        "status": "ok",
        "time": utils.tz_now_str(),
        "service": "shuttle-api"
    }


# ========== 班次資料 API（原 booking-api）==========
@app.get("/api/sheet")
def get_sheet_data(
    sheet: Optional[str] = Query(None, description="工作表名稱"),
    range: Optional[str] = Query(None, description="範圍（A1 表示法）")
):
    """
    讀取 Google Sheets 資料（原 booking-api /api/sheet）
    
    Query Parameters:
        sheet: 工作表名稱，默認為「可預約班次(web)」
        range: 自定義範圍（A1 表示法），例如 'A2:E10'
    """
    try:
        sheet_name = sheet or config.DEFAULT_SHEET
        range_name = range
        
        # 構建範圍字符串
        if range_name:
            if "!" in range_name:
                full_range = range_name
            else:
                full_range = f"{sheet_name}!{range_name}"
        else:
            full_range = f"{sheet_name}!{config.DEFAULT_RANGE}"
        
        # 檢查快取
        cached = cache.get_cached_sheet_data(sheet_name, full_range)
        if cached is not None:
            return cached
        
        # 從 API 讀取
        values = sheets.get_sheet_data_via_api(sheet_name, full_range)
        return values
        
    except Exception as e:
        logger.error(f"Error in /api/sheet: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/realtime/location")
def api_realtime_location():
    """
    讀取 Firebase 中的即時位置資料（原 booking-api /api/realtime/location）
    返回：GPS系統總開關、司機位置、當前班次信息、路線、站點等
    """
    try:
        if not firebase.init_firebase():
            raise HTTPException(status_code=500, detail="Firebase initialization failed")
        
        # 讀取 GPS 系統總開關（優先從 Sheet 的「系統」E19 讀取）
        gps_system_enabled = None
        try:
            values = sheets.get_sheet_data_via_api("系統", "系統!E19")
            if values and len(values) > 0 and len(values[0]) > 0:
                e19_value = (values[0][0] or "").strip().lower()
                gps_system_enabled = e19_value in ("true", "t", "yes", "1")
        except Exception:
            pass
        
        # 如果從 Sheet 讀取失敗，嘗試從 Firebase 讀取
        if gps_system_enabled is None:
            gps_system_enabled = firebase.get_value("/gps_system_enabled")
        
        # 如果都沒有，預設為 False（關閉）
        if gps_system_enabled is None:
            gps_system_enabled = False
        
        # 讀取司機位置
        driver_location = firebase.get_value("/driver_location") or {}
        
        # 讀取當前班次信息
        current_trip_id = firebase.get_value("/current_trip_id") or ""
        current_trip_status = firebase.get_value("/current_trip_status") or ""
        current_trip_datetime = firebase.get_value("/current_trip_datetime") or ""
        current_trip_route = firebase.get_value("/current_trip_route") or {}
        current_trip_stations = firebase.get_value("/current_trip_stations") or {}
        current_trip_station = firebase.get_value("/current_trip_station") or ""
        current_trip_start_time = firebase.get_value("/current_trip_start_time") or 0
        current_trip_completed_stops = firebase.get_value("/current_trip_completed_stops") or []
        last_trip_datetime = firebase.get_value("/last_trip_datetime") or ""
        
        # 自動結束檢查邏輯（從原 booking-api 遷移）
        import time
        if current_trip_status == "active" and current_trip_start_time:
            now_ms = int(time.time() * 1000)
            elapsed_ms = now_ms - int(current_trip_start_time)
            
            if elapsed_ms >= config.AUTO_SHUTDOWN_MS:
                # 自動結束班次
                try:
                    if current_trip_id:
                        firebase.delete_path(f"/trip/{current_trip_id}/route")
                except Exception:
                    pass
                
                firebase.set_value("/current_trip_status", "ended")
                if current_trip_datetime:
                    firebase.set_value("/last_trip_datetime", current_trip_datetime)
                firebase.set_value("/current_trip_id", "")
                firebase.set_value("/current_trip_route", {})
                firebase.set_value("/current_trip_datetime", "")
                firebase.set_value("/current_trip_stations", {})
                
                current_trip_status = "ended"
                if current_trip_datetime:
                    last_trip_datetime = current_trip_datetime
        
        # 獲取 GPS 位置歷史
        current_trip_path_history = []
        try:
            if current_trip_id:
                current_trip_path_history = firebase.get_value("/current_trip_path_history") or []
        except Exception:
            pass
        
        return {
            "gps_system_enabled": bool(gps_system_enabled),
            "driver_location": driver_location,
            "current_trip_id": current_trip_id,
            "current_trip_status": current_trip_status,
            "current_trip_datetime": current_trip_datetime,
            "current_trip_route": current_trip_route,
            "current_trip_stations": current_trip_stations,
            "current_trip_station": current_trip_station,
            "current_trip_start_time": int(current_trip_start_time) if current_trip_start_time else 0,
            "current_trip_completed_stops": current_trip_completed_stops,
            "current_trip_path_history": current_trip_path_history,
            "last_trip_datetime": last_trip_datetime
        }
        
    except Exception as e:
        logger.error(f"Error in /api/realtime/location: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# ========== 預約管理 API（原 booking-manager）==========
@app.options("/api/ops")
@app.options("/api/ops/")
def ops_options():
    """CORS 預檢請求"""
    return Response(status_code=204)


@app.post("/api/ops")
@app.post("/api/ops/")
def ops(req: OpsRequest):
    """
    預約操作 API（原 booking-manager /api/ops）
    支持：book, modify, cancel, query, check_in, mail
    """
    return handle_ops_request(req.action, req.data)


@app.get("/api/qr/{code}")
def get_qr_code(code: str):
    """
    QR Code 生成 API（原 booking-manager /api/qr/{code}）
    返回 QR Code 圖片（PNG 格式）
    """
    try:
        import urllib.parse
        decoded_code = urllib.parse.unquote(code)
        qr_image_bytes = booking.generate_qr_code_image(decoded_code)
        return Response(content=qr_image_bytes, media_type="image/png")
    except Exception as e:
        logger.error(f"Error generating QR code: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"QR 生成失敗: {str(e)}")


# ========== 司機端 API（原 driver-api2）==========
@app.post("/api/driver/location")
def update_driver_location(loc: DriverLocation):
    """更新司機位置（原 driver-api2 /api/driver/location）"""
    return handle_update_driver_location(loc)


@app.get("/api/driver/location")
def get_driver_location():
    """獲取司機位置（原 driver-api2 /api/driver/location）"""
    return handle_get_driver_location()


@app.get("/api/driver/data", response_model=DriverAllData)
def driver_get_all_data():
    """整合端點：一次返回 trips / trip_passengers / passenger_list"""
    return handle_driver_get_all_data()


@app.get("/api/driver/trips")
def driver_get_trips():
    """班次列表"""
    return handle_driver_get_trips()


@app.get("/api/driver/trip_passengers")
def driver_get_trip_passengers(
    trip_id: str = Query(..., description="主班次時間原始字串，例如 2025/12/08 18:30")
):
    """指定班次乘客列表"""
    return handle_driver_get_trip_passengers(trip_id)


@app.get("/api/driver/passenger_list")
def driver_get_passenger_list():
    """乘客清單（出車總覽）"""
    return handle_driver_get_passenger_list()


@app.post("/api/driver/checkin", response_model=DriverCheckinResponse)
def driver_checkin(req: DriverCheckinRequest):
    """掃描 QRCode 後，將該訂單標記為「已上車」"""
    return handle_driver_checkin(req)


@app.post("/api/driver/no_show")
def driver_no_show(req: BookingIdRequest):
    """標記 No-show"""
    return handle_driver_no_show(req)


@app.post("/api/driver/manual_boarding")
def driver_manual_boarding(req: BookingIdRequest):
    """手動登車"""
    return handle_driver_manual_boarding(req)


@app.post("/api/driver/trip_status")
def driver_trip_status(req: TripStatusRequest):
    """更新班次狀態"""
    return handle_driver_trip_status(req)


@app.post("/api/driver/qrcode_info", response_model=QrInfoResponse)
def driver_qrcode_info(req: QrInfoRequest):
    """獲取 QR Code 資訊"""
    return handle_driver_qrcode_info(req)


@app.post("/api/driver/google/trip_start", response_model=GoogleTripStartResponse)
def driver_google_trip_start(req: GoogleTripStartRequest):
    """開始 Google 行程"""
    return handle_google_trip_start(req)


@app.post("/api/driver/google/trip_complete")
def driver_google_trip_complete(req: GoogleTripCompleteRequest):
    """完成 Google 行程"""
    return handle_google_trip_complete(req)


@app.get("/api/driver/route")
def driver_route(trip_id: str = Query(..., description="主班次時間，例如 2025/12/14 14:30")):
    """讀取 Firebase 中該班次的路線資料"""
    return handle_driver_route(trip_id)


@app.get("/api/driver/system_status")
def driver_system_status():
    """讀取 GPS 系統總開關狀態"""
    return handle_driver_system_status()


@app.post("/api/driver/system_status")
def driver_set_system_status(req: SystemStatusRequest):
    """寫入 GPS 系統總開關狀態"""
    return handle_driver_set_system_status(req)


@app.post("/api/driver/update_station")
def driver_update_station(req: UpdateStationRequest):
    """更新當前站點到 Firebase"""
    return handle_driver_update_station(req)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=config.PORT)

