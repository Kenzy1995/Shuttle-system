from flask import Flask, jsonify
from flask_cors import CORS
from google.auth import default
from googleapiclient.discovery import build
import json
import os

app = Flask(__name__)
CORS(app)

SCOPES = ["https://www.googleapis.com/auth/spreadsheets.readonly"]
SPREADSHEET_ID = "1xp54tKOczklmT8uacW-HMxwV8r0VOR2ui33jYcE2pUQ"
RANGE_NAME = "可預約班次(web)!A1:Z"

@app.route("/api/sheet")
def get_sheet_data():
    try:
        # ✅ 在這裡才建立 service，確保 metadata server 已啟動
        credentials, _ = default(scopes=SCOPES)
        service = build("sheets", "v4", credentials=credentials)

        result = (
            service.spreadsheets()
            .values()
            .get(spreadsheetId=SPREADSHEET_ID, range=RANGE_NAME)
            .execute()
        )
        return app.response_class(
            response=json.dumps(result.get("values", []), ensure_ascii=False),
            status=200,
            mimetype="application/json",
        )
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/health")
def health_check():
    return jsonify({"status": "ok"}), 200


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
