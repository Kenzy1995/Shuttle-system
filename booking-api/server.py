from flask import Flask, jsonify, request
from flask_cors import CORS
from google.auth import default
from googleapiclient.discovery import build
import json
import os
import firebase_admin
from firebase_admin import credentials, db


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


@app.route("/api/sheet")
def get_sheet_data():
    """
    Fetches rows from a Google Sheet via the Sheets API.

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
        
        # 讀取 GPS 系統總開關
        gps_system_enabled = db.reference("/gps_system_enabled").get()
        if gps_system_enabled is None:
            gps_system_enabled = True  # 預設啟用
        
        # 讀取司機位置
        driver_location = db.reference("/driver_location").get() or {}
        
        # 讀取當前班次信息
        current_trip_id = db.reference("/current_trip_id").get() or ""
        current_trip_status = db.reference("/current_trip_status").get() or ""
        current_trip_datetime = db.reference("/current_trip_datetime").get() or ""
        current_trip_route = db.reference("/current_trip_route").get() or {}
        current_trip_stations = db.reference("/current_trip_stations").get() or {}
        current_trip_station = db.reference("/current_trip_station").get() or ""  # 即將前往的站點
        last_trip_datetime = db.reference("/last_trip_datetime").get() or ""
        
        return jsonify({
            "gps_system_enabled": bool(gps_system_enabled),
            "driver_location": driver_location,
            "current_trip_id": current_trip_id,
            "current_trip_status": current_trip_status,
            "current_trip_datetime": current_trip_datetime,
            "current_trip_route": current_trip_route,
            "current_trip_stations": current_trip_stations,
            "current_trip_station": current_trip_station,  # 即將前往的站點
            "last_trip_datetime": last_trip_datetime
        }), 200
    except Exception as e:
        print(f"Realtime location read error: {e}")
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
