from flask import Flask, jsonify, request
from flask_cors import CORS
from google.auth import default
from googleapiclient.discovery import build
import json
import os
import firebase_admin
from firebase_admin import credentials, db
from datetime import datetime
from threading import Lock

app = Flask(__name__)
CORS(app, origins=[
    "https://hotel-web-3addcbkbgq-de.a.run.app",
    "https://hotel-web-995728097341.asia-east1.run.app",
])

# Scopes and spreadsheet ID for Google Sheets
SCOPES = ["https://www.googleapis.com/auth/spreadsheets.readonly"]
SPREADSHEET_ID = "1xp54tKOczklmT8uacW-HMxwV8r0VOR2ui33jYcE2pUQ"

# Default sheet and range values.  The default sheet corresponds to the
# available shuttle schedules as used by the front‑end.  When a client
# requests a different sheet via the `sheet` query parameter, the range
# will be applied to that sheet instead.
DEFAULT_SHEET = "可預約班次(web)"
DEFAULT_RANGE = "A1:Z"

# ========= 快取設定 =========
# 目標：在 5 秒 TTL 內，所有讀取 API 都共用同一份 Sheet 資料，避免重複打 Google Sheets
CACHE_TTL_SECONDS = 5

# SHEET_CACHE 結構：
# {
#   "values": List[List[str]] 或 None,
#   "fetched_at": datetime 或 None,
#   "sheet_name": str 或 None,
#   "range_name": str 或 None
# }
SHEET_CACHE: dict = {
    "values": None,
    "fetched_at": None,
    "sheet_name": None,
    "range_name": None
}
CACHE_LOCK = Lock()


def _get_cached_sheet_data(sheet_name: str, range_name: str):
    """
    取得快取的 Sheet 資料
    在 CACHE_TTL_SECONDS 內，如果 cache 有值且 sheet_name 和 range_name 匹配，直接回傳 cache。
    超過 TTL 或 cache 無效時，返回 None 表示需要重新讀取。
    """
    now = datetime.now()
    global SHEET_CACHE

    with CACHE_LOCK:
        cached_values = SHEET_CACHE.get("values")
        cached_sheet = SHEET_CACHE.get("sheet_name")
        cached_range = SHEET_CACHE.get("range_name")
        fetched_at = SHEET_CACHE.get("fetched_at")

        if (
            cached_values is not None
            and cached_sheet == sheet_name
            and cached_range == range_name
            and fetched_at is not None
            and (now - fetched_at).total_seconds() < CACHE_TTL_SECONDS
        ):
            # 使用快取
            return cached_values

        # 需要重新讀取
        return None


def _set_cached_sheet_data(sheet_name: str, range_name: str, values: list):
    """更新快取"""
    global SHEET_CACHE
    with CACHE_LOCK:
        SHEET_CACHE = {
            "values": values,
            "fetched_at": datetime.now(),
            "sheet_name": sheet_name,
            "range_name": range_name
        }


@app.route("/api/sheet")
def get_sheet_data():
    """
    Fetches rows from a Google Sheet via the Sheets API.
    優化：添加 5 秒快取機制，減少 Google Sheets API 調用

    Optional query parameters:
    - sheet: Name of the sheet tab to query.  Defaults to the
      `DEFAULT_SHEET`.
    - range: A custom A1 notation range (e.g. 'A2:E10').  When
      provided together with `sheet`, the final range will be
      `<sheet>!<range>`.  When provided without `sheet`, the range will
      be applied to the default sheet.

    Always returns a JSON array of rows (even if empty) with UTF‑8
    encoding.  On error, returns a JSON object with an `error`
    property and HTTP status 500.
    """
    # Determine which sheet to read from and the A1 range to use.
    sheet = request.args.get("sheet", DEFAULT_SHEET)
    custom_range = request.args.get("range")
    if custom_range:
        range_name = f"{sheet}!{custom_range}"
    else:
        range_name = f"{sheet}!{DEFAULT_RANGE}"

    # 檢查快取
    cached_values = _get_cached_sheet_data(sheet, range_name)
    if cached_values is not None:
        return app.response_class(
            response=json.dumps(cached_values, ensure_ascii=False),
            status=200,
            mimetype="application/json",
        )

    try:
        # Lazily construct the Sheets API client here.  This avoids
        # issues in certain hosting environments where credentials are
        # unavailable at import time.
        credentials, _ = default(scopes=SCOPES)
        service = build("sheets", "v4", credentials=credentials)
        result = (
            service.spreadsheets()
            .values()
            .get(spreadsheetId=SPREADSHEET_ID, range=range_name)
            .execute()
        )
        values = result.get("values", [])
        
        # 更新快取
        _set_cached_sheet_data(sheet, range_name, values)
        
        return app.response_class(
            response=json.dumps(values, ensure_ascii=False),
            status=200,
            mimetype="application/json",
        )
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/health")
def health_check():
    """Simple health check endpoint."""
    return jsonify({"status": "ok"}), 200


def _init_firebase():
    """初始化 Firebase Admin SDK"""
    try:
        if not firebase_admin._apps:
            service_account_path = "service-account.json"
            if os.path.exists(service_account_path):
                cred = credentials.Certificate(service_account_path)
            else:
                cred = credentials.ApplicationDefault()
            db_url = os.environ.get("FIREBASE_RTDB_URL")
            if not db_url:
                project_id = os.environ.get("GOOGLE_CLOUD_PROJECT", "forte-booking-system")
                db_url = f"https://{project_id}-default-rtdb.asia-southeast1.firebasedatabase.app/"
            firebase_admin.initialize_app(cred, {"databaseURL": db_url})
        return True
    except Exception as e:
        print(f"Firebase init error: {e}")
        return False


@app.route("/api/realtime/location", methods=["GET"])
def api_realtime_location():
    """
    讀取 Firebase 中的即時位置資料
    返回：GPS系統總開關、司機位置、當前班次信息、路線、站點等
    """
    try:
        if not _init_firebase():
            return jsonify({"error": "Firebase initialization failed"}), 500
        
        # 讀取 GPS 系統總開關（優先從 Sheet 的「系統」E19 讀取）
        # 優化：添加快取機制，減少 Sheet 讀取
        gps_system_enabled = None
        try:
            # 檢查快取（系統開關變化不頻繁，可以快取更長時間）
            cached_gps_enabled = _get_cached_sheet_data("系統", "系統!E19")
            if cached_gps_enabled is None:
                # 從 Google Sheet 的「系統」分頁 E19 讀取
                credentials, _ = default(scopes=SCOPES)
                service = build("sheets", "v4", credentials=credentials)
                result = (
                    service.spreadsheets()
                    .values()
                    .get(spreadsheetId=SPREADSHEET_ID, range="系統!E19")
                    .execute()
                )
                values = result.get("values", [])
                if values and len(values) > 0 and len(values[0]) > 0:
                    e19_value = (values[0][0] or "").strip().lower()
                    gps_system_enabled = e19_value in ("true", "t", "yes", "1")
                    # 更新快取
                    _set_cached_sheet_data("系統", "系統!E19", values)
            else:
                # 使用快取
                if cached_gps_enabled and len(cached_gps_enabled) > 0 and len(cached_gps_enabled[0]) > 0:
                    e19_value = (cached_gps_enabled[0][0] or "").strip().lower()
                    gps_system_enabled = e19_value in ("true", "t", "yes", "1")
        except Exception as e:
            print(f"Read GPS system enabled from Sheet error: {e}")
        
        # 如果從 Sheet 讀取失敗，嘗試從 Firebase 讀取
        if gps_system_enabled is None:
            gps_system_enabled = db.reference("/gps_system_enabled").get()
        
        # 如果都沒有，預設為 False（關閉）
        if gps_system_enabled is None:
            gps_system_enabled = False
        
        # 讀取司機位置
        driver_location = db.reference("/driver_location").get() or {}
        
        # 讀取當前班次信息
        current_trip_id = db.reference("/current_trip_id").get() or ""
        current_trip_status = db.reference("/current_trip_status").get() or ""
        current_trip_datetime = db.reference("/current_trip_datetime").get() or ""
        current_trip_route = db.reference("/current_trip_route").get() or {}
        current_trip_stations = db.reference("/current_trip_stations").get() or {}
        current_trip_station = db.reference("/current_trip_station").get() or ""  # 即將前往的站點
        current_trip_start_time = db.reference("/current_trip_start_time").get() or 0  # 發車時間戳（毫秒）
        current_trip_completed_stops = db.reference("/current_trip_completed_stops").get() or []  # 已到達站點列表
        last_trip_datetime = db.reference("/last_trip_datetime").get() or ""
        
        # 方案 2：自動檢查過期班次（基於發車時間和 GPS 更新時間）
        # 前端讀取資料時檢查，如果發車時間超過 40 分鐘，自動結束班次
        try:
            import time
            # 檢查基於發車時間
            if current_trip_status == "active" and current_trip_start_time:
                now_ms = int(time.time() * 1000)
                elapsed_ms = now_ms - int(current_trip_start_time)
                AUTO_SHUTDOWN_MS = 40 * 60 * 1000  # 40分鐘
                
                # 如果超過 40 分鐘，自動結束（只更新 Firebase，Sheet 由 driver-api2 處理）
                if elapsed_ms >= AUTO_SHUTDOWN_MS:
                    print(f"Auto-completing trip in booking-api: {current_trip_id} (elapsed: {elapsed_ms/1000/60:.1f} minutes)")
                    # 優化：清理歷史路線資料，節省 Firebase 儲存空間
                    try:
                        if current_trip_id:
                            history_route_ref = db.reference(f"/trip/{current_trip_id}/route")
                            history_route_ref.delete()
                            print(f"Cleaned up historical route data for trip: {current_trip_id}")
                    except Exception as cleanup_error:
                        print(f"Historical route cleanup error (non-critical): {cleanup_error}")
                    
                    # 更新 Firebase 狀態為 ended
                    db.reference("/current_trip_status").set("ended")
                    # 保存最後一次班次的日期時間
                    if current_trip_datetime:
                        db.reference("/last_trip_datetime").set(current_trip_datetime)
                    # 清除其他標記
                    db.reference("/current_trip_id").set("")
                    db.reference("/current_trip_route").set({})
                    db.reference("/current_trip_datetime").set("")
                    db.reference("/current_trip_stations").set({})
                    # 更新狀態變數
                    current_trip_status = "ended"
                    if current_trip_datetime:
                        last_trip_datetime = current_trip_datetime
            
            # 檢查基於 GPS 更新時間（如果 GPS 超過 15 分鐘沒有更新，且班次狀態為 active）
            # 注意：這個檢查只在第一個檢查沒有觸發時執行（即 current_trip_status 仍然是 "active"）
            if current_trip_status == "active":
                driver_location_updated_at = driver_location.get("updated_at") if driver_location else None
                if driver_location_updated_at and current_trip_start_time:
                    try:
                        # 解析 updated_at 時間（格式：YYYY-MM-DD HH:MM:SS）
                        from datetime import datetime
                        updated_dt = datetime.strptime(driver_location_updated_at, "%Y-%m-%d %H:%M:%S")
                        now_dt = datetime.now()
                        elapsed_seconds = (now_dt - updated_dt).total_seconds()
                        GPS_TIMEOUT_SECONDS = 15 * 60  # 15分鐘
                        
                        # 如果 GPS 超過 15 分鐘沒有更新，且發車時間超過 40 分鐘，自動結束
                        if elapsed_seconds >= GPS_TIMEOUT_SECONDS:
                            now_ms = int(time.time() * 1000)
                            elapsed_ms = now_ms - int(current_trip_start_time)
                            AUTO_SHUTDOWN_MS = 40 * 60 * 1000  # 40分鐘
                            
                            if elapsed_ms >= AUTO_SHUTDOWN_MS:
                                print(f"Auto-completing trip (GPS timeout): {current_trip_id} (GPS not updated for {elapsed_seconds/60:.1f} minutes)")
                                # 改進：清理當前班次的路徑歷史資料
                                try:
                                    db.reference("/current_trip_path_history").set([])
                                    print(f"Cleaned up path history data for trip")
                                except Exception as cleanup_error:
                                    print(f"Path history cleanup error (non-critical): {cleanup_error}")
                                
                                # 更新 Firebase 狀態為 ended
                                db.reference("/current_trip_status").set("ended")
                                if current_trip_datetime:
                                    db.reference("/last_trip_datetime").set(current_trip_datetime)
                                db.reference("/current_trip_id").set("")
                                db.reference("/current_trip_route").set({})
                                db.reference("/current_trip_datetime").set("")
                                db.reference("/current_trip_stations").set({})
                                db.reference("/current_trip_path_history").set([])
                                # 更新狀態變數
                                current_trip_status = "ended"
                                if current_trip_datetime:
                                    last_trip_datetime = current_trip_datetime
                    except Exception as parse_error:
                        print(f"Parse GPS updated_at error: {parse_error}")
        except Exception as auto_complete_error:
            print(f"Auto-complete check error in booking-api: {auto_complete_error}")
        
        # 獲取GPS位置歷史（用於路線追蹤）
        current_trip_path_history = []
        try:
            if current_trip_id:
                path_history_ref = db.reference("/current_trip_path_history")
                current_trip_path_history = path_history_ref.get() or []
        except Exception as path_history_error:
            print(f"Path history read error: {path_history_error}")
        
        return jsonify({
            "gps_system_enabled": bool(gps_system_enabled),
            "driver_location": driver_location,
            "current_trip_id": current_trip_id,
            "current_trip_status": current_trip_status,
            "current_trip_datetime": current_trip_datetime,
            "current_trip_route": current_trip_route,
            "current_trip_stations": current_trip_stations,
            "current_trip_station": current_trip_station,  # 即將前往的站點
            "current_trip_start_time": int(current_trip_start_time) if current_trip_start_time else 0,  # 發車時間戳
            "current_trip_completed_stops": current_trip_completed_stops,  # 已到達站點列表
            "current_trip_path_history": current_trip_path_history,  # GPS位置歷史（用於路線追蹤）
            "last_trip_datetime": last_trip_datetime
        }), 200
    except Exception as e:
        print(f"Realtime location read error: {e}")
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
