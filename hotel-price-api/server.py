import datetime
import os
import traceback
from zoneinfo import ZoneInfo

from fastapi import FastAPI, Query
from fastapi.responses import JSONResponse

from playwright.async_api import async_playwright

from google.oauth2 import service_account
from googleapiclient.discovery import build


# ========= Google Sheets 設定 =========
SPREADSHEET_ID = "1dbJ0jZAG0fcI3-TAYiIm-C2HO1Cb3YHUVBKvlAAJVAg"
ADR_SHEET = "ADR"
DATA_SHEET = "Data"
START_ROW = 3

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]


def get_sheets_service():
    """取得 Google Sheets API client（用 Cloud Run service account 或掛載的 key.json）"""
    creds_path = "/var/secrets/google/key.json"

    try:
        if os.path.exists(creds_path):
            creds = service_account.Credentials.from_service_account_file(
                creds_path, scopes=SCOPES
            )
        else:
            import google.auth
            creds, _ = google.auth.default(scopes=SCOPES)

        return build("sheets", "v4", credentials=creds)

    except Exception as e:
        raise RuntimeError(f"Failed to init Sheets API: {e}")


# ========= Playwright 抓 Google Maps 價格 =========
async def fetch_price(url: str) -> str:
    """用 Playwright 開啟 Google Maps 頁面，抓第一個 span.Cbys4b 的文字"""
    browser = None

    # 確保不被外部環境變數干擾，強制用 Playwright 內建的 Chromium
    for var in ("CHROME_PATH", "GOOGLE_CHROME_SHIM", "PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH"):
        os.environ.pop(var, None)

    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=True,
                args=[
                    "--no-sandbox",
                    "--disable-setuid-sandbox",
                    "--disable-gpu",
                    "--disable-dev-shm-usage",
                ],
            )
            page = await browser.new_page()

            # 載入頁面，等到 networkidle（大部分 XHR 都跑完）
            await page.goto(url, timeout=60000, wait_until="networkidle")

            selector = "span.Cbys4b"

            # 等價格出現
            await page.wait_for_selector(selector, timeout=10000)
            value = await page.inner_text(selector)

            return value.strip()

    except Exception as e:
        # 這裡直接回傳錯誤字串，方便在 Data 表上看到是哪邊出事
        return f"ERROR: {e}"

    finally:
        if browser:
            await browser.close()


# ========= FastAPI =========
app = FastAPI()


@app.get("/price")
async def get_price(url: str = Query(..., description="Google Maps 飯店網址")):
    """
    單筆查價：?url=...
    回傳 {url, price}
    """
    try:
        price = await fetch_price(url)
        return {"url": url, "price": price}
    except Exception as e:
        return JSONResponse(
            {
                "error": str(e),
                "trace": traceback.format_exc(),
            },
            status_code=500,
        )


@app.get("/run")
async def run_all():
    """
    取代原本 Apps Script 的 updatePrices():
    - 從 ADR!A3:B 讀「飯店名稱 / URL」
    - 逐筆用 Playwright 抓價格
    - 寫入 Data!A:C（日期時間 / 飯店 / 價格）
    """
    try:
        sheets = get_sheets_service()

        # 讀 ADR!A3:B
        adr_range = f"{ADR_SHEET}!A{START_ROW}:B"
        rows = (
            sheets.spreadsheets()
            .values()
            .get(spreadsheetId=SPREADSHEET_ID, range=adr_range)
            .execute()
            .get("values", [])
        )

        results = []
        tz = ZoneInfo("Asia/Taipei")
        now = datetime.datetime.now(tz)
        now_str = now.strftime("%Y/%m/%d %H:%M")

        

        for row in rows:
            if len(row) < 2:
                continue

            name = (row[0] or "").strip()
            url = (row[1] or "").strip()

            if not name or not url.startswith("http"):
                continue

            price = await fetch_price(url)
            results.append([now_str, name, price])

        # 寫入 Data!A:C
        if results:
            data_range = f"{DATA_SHEET}!A:C"
            body = {"values": results}
            sheets.spreadsheets().values().append(
                spreadsheetId=SPREADSHEET_ID,
                range=data_range,
                valueInputOption="USER_ENTERED",
                insertDataOption="INSERT_ROWS",
                body=body,
            ).execute()

        return {
            "status": "ok",
            "updated_rows": len(results),
            "data": results,
        }

    except Exception as e:
        return JSONResponse(
            {
                "error": str(e),
                "trace": traceback.format_exc(),
            },
            status_code=500,
        )


@app.get("/")
def root():
    return {"message": "Hotel Price Playwright API is running"}
