# server.py
import os
import re
import datetime
import requests
from fastapi import FastAPI, Query
from fastapi.responses import JSONResponse

from google.oauth2 import service_account
from googleapiclient.discovery import build

# ============================
# 設定
# ============================
SPREADSHEET_ID = "1dbJ0jZAG0fcI3-TAYiIm-C2HO1Cb3YHUVBKvlAAJVAg"
ADR_SHEET = "ADR"
DATA_SHEET = "Data"
START_ROW = 3
CLASS_KEY = "Cbys4b"

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

# Cloud Run service account 自動讀取 metadata 取得 credentials
def get_sheets_service():
    creds = service_account.Credentials.from_service_account_file(
        "/var/secrets/google/key.json", scopes=SCOPES
    ) if os.path.exists("/var/secrets/google/key.json") else None

    # 若 Cloud Run 用 IAM 身分跑，使用默認 credentials
    if creds is None:
        import google.auth
        creds, _ = google.auth.default(scopes=SCOPES)

    return build("sheets", "v4", credentials=creds)


# ============================
# FastAPI
# ============================
app = FastAPI()

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36"
    ),
    "Accept-Language": "zh-TW,zh;q=0.9,en;q=0.8"
}

# ============================
# 工具：抓 HTML
# ============================
def fetch_html(url: str) -> str:
    resp = requests.get(url, headers=HEADERS, timeout=15)
    resp.raise_for_status()
    return resp.text

# ============================
# 工具：從 HTML 抓價格
# ============================
def extract_price(html: str) -> str:
    pattern = rf'<span\b[^>]*class="[^"]*\b{CLASS_KEY}\b[^"]*"[^>]*>([\s\S]*?)<\/span>'
    match = re.search(pattern, html, flags=re.IGNORECASE)

    if not match:
        return "N/A"

    raw = re.sub(r"<[^>]+>", "", match.group(1)).strip()

    clean = re.findall(r"(NT\$|\$|€|£|¥)?\s*([0-9,]+)", raw)
    if not clean:
        return raw

    currency, number = clean[0]
    number = number.replace(",", "")
    return f"{currency}{number}" if currency else number

# ============================
# API：單筆查詢
# ============================
@app.get("/price")
def get_price(url: str = Query(...)):
    try:
        html = fetch_html(url)
        price = extract_price(html)
        return {"url": url, "price": price}
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


# ============================
# API：取代 Google Apps Script updatePrices()
# ============================
@app.get("/run")
def run_all():
    sheets = get_sheets_service()

    # 讀 ADR!A3:B（飯店名稱、網址）
    adr_range = f"{ADR_SHEET}!A{START_ROW}:B"
    rows = sheets.spreadsheets().values().get(
        spreadsheetId=SPREADSHEET_ID, range=adr_range
    ).execute().get("values", [])

    results = []
    now = datetime.datetime.now().strftime("%Y/%m/%d %H:%M")

    for idx, row in enumerate(rows):
        if len(row) < 2:
            continue

        name = row[0].strip()
        url = row[1].strip()

        if not url.startswith("http"):
            continue

        try:
            html = fetch_html(url)
            price = extract_price(html)
        except Exception:
            price = "N/A"

        results.append([now, name, price])

    # 寫入 Data!A:C（追加）
    if results:
        data_range = f"{DATA_SHEET}!A:C"
        body = {"values": results}
        sheets.spreadsheets().values().append(
            spreadsheetId=SPREADSHEET_ID,
            range=data_range,
            valueInputOption="USER_ENTERED",
            insertDataOption="INSERT_ROWS",
            body=body
        ).execute()

    return {
        "status": "ok",
        "updated_rows": len(results),
        "message": "Update completed",
        "data": results
    }


@app.get("/")
def root():
    return {"message": "Hotel Price API is running"}
