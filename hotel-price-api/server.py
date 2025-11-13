# server.py
import re
import requests
from fastapi import FastAPI, Query
from bs4 import BeautifulSoup
from fastapi.responses import JSONResponse

app = FastAPI()

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36",
    "Accept-Language": "zh-TW,zh;q=0.9,en;q=0.8"
}

def fetch_html(url: str) -> str:
    resp = requests.get(url, headers=HEADERS, timeout=15)
    resp.raise_for_status()
    return resp.text

def extract_price(html: str) -> str:
    pattern = r'<span\b[^>]*class="[^"]*\bCbys4b\b[^"]*"[^>]*>([\s\S]*?)<\/span>'
    match = re.search(pattern, html, flags=re.IGNORECASE)

    if not match:
        return "N/A"

    raw = re.sub(r"<[^>]+>", "", match.group(1)).trim()
    clean = re.findall(r"(NT\$|\$|€|£|¥)?\s*([0-9,]+)", raw)

    if not clean:
        return raw

    currency, number = clean[0]
    number = number.replace(",", "")
    return f"{currency}{number}" if currency else number

@app.get("/price")
def get_price(url: str = Query(...)):
    try:
        html = fetch_html(url)
        price = extract_price(html)
        return {"url": url, "price": price}
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)

@app.get("/")
def root():
    return {"message": "Hotel Price API is running"}
