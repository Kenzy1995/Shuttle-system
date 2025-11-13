import asyncio
import datetime
import os
import re
from fastapi import FastAPI, Query
from fastapi.responses import JSONResponse

from playwright.async_api import async_playwright

from google.oauth2 import service_account
from googleapiclient.discovery import build


# ======== Google Sheets 設定 ========
SPREADSHEET_ID = "1dbJ0jZAG0fcI3-TAYiIm-C2HO1Cb3YHUVBKvlAAJVAg"
ADR_SHEET = "ADR"
DATA_SHEET = "Data"
START_ROW = 3

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]


def get_sheets_service():
    creds_path = "/var/secrets/google/key.json"

    if os.path.exists(creds_path):
        creds = service_account.Credentials.from_service_account_file(
            creds_path, scopes=SCOPES
        )
    else:
        import google.auth
        creds, _ = google.auth.default(scopes=SCOPES)

    return build("sheets", "v4", credentials=creds)


# ======== Playwright 抓 Google Maps 價格 ========
async def fetch_price(url: str) -> str:
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-gpu"]
        )
        page = await browser.new_page()

        await page.goto(url, timeout=60000, wait_until="networkidle")

        # Google Maps 的價格 class
        selector = "span.Cbys4b"

        try:
            await page.wait_for_selector(selector, timeout=10000)
            value = await page.inner_text(selector)
        except:
            await browser.close()
            return "N/A"

        await browser.close()
        return value.strip()


# ======== FastAPI ========
app = FastAPI()


@app.get("/price")
async def get_price(url: str = Query(...)):
    try:
        price = await fetch_price(url)
        return {"url": url, "price": price}
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


# ======== /run → 取代 Apps Script updatePrices() ========
@app.get("/run")
async def run_all():
    sheets = get_sheets_service()

    adr_range = f"{ADR_SHEET}!A{START_ROW}:B"
    rows = sheets.spreadsheets().values().get(
        spreadsheetId=SPREADSHEET_ID,
        range=adr_range
    ).execute().get("values", [])

    results = []
    now = datetime.datetime.now().strftime("%Y/%m/%d %H:%M")

    for row in rows:
        if len(row) < 2:
            continue

        name = row[0].strip()
        url = row[1].strip()

        if not url.startswith("http"):
            continue

        price = await fetch_price(url)
        results.append([now, name, price])

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
        "data": results
    }


@app.get("/")
def root():
    return {"message": "Hotel Price Playwright API is running"}
