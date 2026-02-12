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
from modules import firebase, sheets, cache, utils

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
# 注意：預約管理功能較複雜，將在下一階段完整遷移
# 這裡先提供框架

@app.post("/api/ops")
@app.post("/api/ops/")
def ops(req: Dict[str, Any]):
    """
    預約操作 API（原 booking-manager /api/ops）
    支持：book, modify, cancel, query
    
    注意：此功能將在下一階段完整遷移
    """
    # TODO: 遷移完整的預約管理邏輯
    return {"message": "預約管理功能遷移中，請稍後..."}


@app.get("/api/qr/{code}")
def get_qr_code(code: str):
    """
    QR Code 生成 API（原 booking-manager /api/qr/{code}）
    
    注意：此功能將在下一階段完整遷移
    """
    # TODO: 遷移 QR Code 生成邏輯
    return {"message": "QR Code 功能遷移中，請稍後..."}


# ========== 司機端 API（原 driver-api2）==========
# 注意：司機端功能較複雜，將在下一階段完整遷移
# 這裡先提供框架

@app.post("/api/driver/location")
def update_driver_location(data: Dict[str, Any]):
    """
    更新司機位置（原 driver-api2 /api/driver/location）
    
    注意：此功能將在下一階段完整遷移
    """
    # TODO: 遷移司機位置更新邏輯
    return {"message": "司機位置更新功能遷移中，請稍後..."}


@app.get("/api/driver/location")
def get_driver_location():
    """
    獲取司機位置（原 driver-api2 /api/driver/location）
    
    注意：此功能將在下一階段完整遷移
    """
    # TODO: 遷移司機位置獲取邏輯
    return {"message": "司機位置獲取功能遷移中，請稍後..."}


# 其他司機端 API 將在後續階段遷移
# TODO: 遷移所有 driver-api2 的端點


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=config.PORT)

