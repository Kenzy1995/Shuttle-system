from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import gspread
from google.oauth2.service_account import Credentials
from datetime import datetime
import qrcode
import io
import base64
import json
from typing import Dict, Any, Tuple
import os

app = FastAPI(title="飯店接駁車預約管理 API")

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Google Sheets
SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
SPREADSHEET_ID = "1xp54tKOczklmT8uacW-HMxwV8r0VOR2ui33jYcE2pUQ"
SHEET_NAME = "預約審核(櫃台)"

# 路線映射（循環路線，飯店會有 1 與 5 的概念）
STATION_ROUTE_MAP = {
    "福泰大飯店 Forte Hotel": 1,
    "南港展覽館-捷運3號出口 / Nangang Exhibition Center - MRT Exit 3": 2,
    "南港火車站 / Nangang Train Station": 3,
    "南港 LaLaport Shopping Park": 4,
}

def get_credentials():
    """取得 Google Sheets 憑證"""
    try:
        creds_env = os.getenv("GOOGLE_CREDENTIALS_JSON")
        if creds_env:
            creds_json = json.loads(creds_env)
        else:
            with open("credentials.json", "r") as f:
                creds_json = json.load(f)
        creds = Credentials.from_service_account_info(creds_json, scopes=SCOPES)
        return gspread.authorize(creds)
    except Exception as e:
        print(f"[ERROR] 憑證初始化失敗: {e}")
        return None

def get_sheet():
    """取得 Google Sheet 工作表"""
    try:
        client = get_credentials()
        if not client:
            raise Exception("無法建立 Google 憑證")
        sheet = client.open_by_key(SPREADSHEET_ID).worksheet(SHEET_NAME)
        return sheet
    except Exception as e:
        print(f"[ERROR] 取得工作表失敗: {e}")
        return None

def generate_booking_id(sheet) -> str:
    """生成預約編號: YYMMDD + 3位序號"""
    try:
        booking_ids = sheet.col_values(1)[1:]  # A 欄（跳過表頭）
        today_prefix = datetime.now().strftime('%y%m%d')
        today_bookings = [bid for bid in booking_ids if bid and bid.startswith(today_prefix)]
        return f"{today_prefix}{len(today_bookings) + 1:03d}"
    except Exception as e:
        print(f"[ERROR] 生成預約編號失敗: {e}")
        return f"BK{int(datetime.now().timestamp())}"

def generate_qr_code(payload: Dict[str, Any]) -> Tuple[str, str]:
    """生成 QR Code，回傳 (base64_image, qr_json_str)"""
    try:
        qr_data = {**payload, "timestamp": datetime.now().isoformat()}
        qr = qrcode.QRCode(version=1, box_size=10, border=5)
        qr.add_data(json.dumps(qr_data, ensure_ascii=False))
        qr.make(fit=True)
        img = qr.make_image(fill_color="black", back_color="white")
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        img_b64 = base64.b64encode(buf.getvalue()).decode()
        return f"data:image/png;base64,{img_b64}", json.dumps(qr_data, ensure_ascii=False)
    except Exception as e:
        print(f"[ERROR] 生成 QR Code 失敗: {e}")
        return "", ""

def calculate_station_indexes(pickup: str, dropoff: str) -> Tuple[int, int]:
    """計算上/下車索引（循環）"""
    try:
        p_idx = STATION_ROUTE_MAP.get(pickup, 0)
        d_idx = STATION_ROUTE_MAP.get(dropoff, 0)

        # 飯店作為循環點的處理：回程到飯店標記為 5
        if pickup == "福泰大飯店 Forte Hotel":
            if dropoff == "福泰大飯店 Forte Hotel":
                p_idx, d_idx = 1, 5
            else:
                p_idx = 1
        elif dropoff == "福泰大飯店 Forte Hotel":
            d_idx = 5

        return p_idx, d_idx
    except Exception as e:
        print(f"[ERROR] 計算站點索引失敗: {e}")
        return 0, 0

def calculate_route_range(p_idx: int, d_idx: int) -> str:
    """計算涉及路段範圍（字串 1,2,3…）"""
    try:
        if not p_idx or not d_idx:
            return ""
        if p_idx <= d_idx:
            seq = list(range(p_idx, d_idx + 1))
        else:
            # 跨循環點
            seq = list(range(p_idx, 6)) + list(range(1, d_idx + 1))
        return ",".join(str(i) for i in seq)
    except Exception as e:
        print(f"[ERROR] 計算路段範圍失敗: {e}")
        return ""

def determine_direction(pickup: str, dropoff: str) -> str:
    """依上下車站點判斷方向"""
    if pickup == "福泰大飯店 Forte Hotel" and dropoff != pickup:
        return "去程"
    if dropoff == "福泰大飯店 Forte Hotel" and pickup != dropoff:
        return "回程"
    if pickup == "福泰大飯店 Forte Hotel" and dropoff == pickup:
        return "循環"
    # 其他站點間移動（理論上不會出現在對外預約）
    p = STATION_ROUTE_MAP.get(pickup, 0)
    d = STATION_ROUTE_MAP.get(dropoff, 0)
    if p and d:
        return "順向" if p < d else "逆向"
    return "未知"

@app.post("/api/book")
async def submit_booking(booking_data: Dict[str, Any]):
    """提交新預約（寫入 A~W 欄）"""
    try:
        sheet = get_sheet()
        if not sheet:
            raise HTTPException(status_code=500, detail="無法連接資料庫")

        booking_id = generate_booking_id(sheet)
        apply_date = datetime.now().strftime("%Y/%m/%d %H:%M")

        pickup = booking_data.get("pickLocation", "")
        dropoff = booking_data.get("dropLocation", "")
        direction = determine_direction(pickup, dropoff)
        p_idx, d_idx = calculate_station_indexes(pickup, dropoff)
        route_range = calculate_route_range(p_idx, d_idx)

        qr_image, qr_json = generate_qr_code({
            "booking_id": booking_id,
            "name": booking_data.get("name", ""),
            "date": booking_data.get("date", ""),
            "time": booking_data.get("time", ""),
            "direction": direction,
            "pickup_station": pickup,
            "dropoff_station": dropoff,
            "passengers": booking_data.get("passengers", 1),
            "phone": booking_data.get("phone", ""),
            "email": booking_data.get("email", ""),
            "identity": booking_data.get("identity", ""),
        })

        # A~W 欄位
        row = [
            booking_id,                    # A 預約編號
            apply_date,                    # B 申請日期
            "✔️ 已預約 Booked",           # C 預約狀態
            booking_data.get("name", ""),  # D 姓名
            booking_data.get("phone", ""), # E 手機
            booking_data.get("email", ""), # F 信箱
            "住宿" if booking_data.get("identity") == "hotel" else "用餐",  # G 身分
            booking_data.get("roomNumber", ""),           # H 房號
            booking_data.get("checkIn", ""),              # I 入住日期
            booking_data.get("checkOut", ""),             # J 退房日期
            booking_data.get("diningDate", ""),           # K 用餐日期
            direction,                                    # L 往返
            pickup,                                       # M 上車地點
            dropoff,                                      # N 下車地點
            f"{booking_data.get('date','')} {booking_data.get('time','')}",  # O 車次
            str(booking_data.get("passengers", 1)),       # P 預約人數
            str(p_idx),                                   # Q 上車索引
            str(d_idx),                                   # R 下車索引
            route_range,                                  # S 涉及路段範圍
            "",                                           # T 確認人數（由公式或人工填）
            "",                                           # U 櫃台審核
            "",                                           # V 備註
            qr_json,                                      # W QR資料
        ]

        # 寫入（用 USER_ENTERED 比較直覺）
        sheet.append_row(row, value_input_option="USER_ENTERED")

        # 回傳前端需要的欄位（保持你原本前端使用）
        return JSONResponse({
            "status": "success",
            "booking_id": booking_id,
            "qr_url": qr_image,
            "message": "預約成功",
        })
    except Exception as e:
        print(f"[ERROR] 預約提交失敗: {e}")
        raise HTTPException(status_code=500, detail=f"預約失敗: {e}")

@app.post("/api/query-orders")
async def query_orders(query_data: Dict[str, Any]):
    """
    查詢個人預約記錄
    ※ 回傳「純陣列」資料，符合前端 Array.isArray(data) 的使用方式
    """
    try:
        sheet = get_sheet()
        if not sheet:
            raise HTTPException(status_code=500, detail="無法連接資料庫")

        booking_id = (query_data.get("booking_id") or "").strip()
        phone = (query_data.get("phone") or "").strip()
        email = (query_data.get("email") or "").strip()

        if not any([booking_id, phone, email]):
            # 前端會自行顯示提示，這裡回傳空陣列即可
            return JSONResponse([])

        # 表頭在第 2 列
        records = sheet.get_all_records(head=2)
        results = []

        for r in records:
            match_bid = booking_id and str(r.get("預約編號", "")).strip() == booking_id
            match_phone = phone and str(r.get("手機", "")).strip() == phone
            match_email = email and str(r.get("信箱", "")).strip() == email
            if match_bid or match_phone or match_email:
                # 直接回傳表格原始欄位資料（前端就是用這些鍵）
                results.append(r)

        # 純陣列回傳，無 status/data 外層
        return JSONResponse(results)
    except Exception as e:
        print(f"[ERROR] 查詢訂單失敗: {e}")
        raise HTTPException(status_code=500, detail=f"查詢失敗: {e}")

@app.post("/api/update-booking")
async def update_booking(update_data: Dict[str, Any]):
    """修改預約人數（P 欄）"""
    try:
        sheet = get_sheet()
        if not sheet:
            raise HTTPException(status_code=500, detail="無法連接資料庫")

        booking_id = update_data.get("booking_id")
        new_passengers = update_data.get("passengers")
        if not booking_id or not new_passengers:
            raise HTTPException(status_code=400, detail="缺少必要參數")

        records = sheet.get_all_records(head=2)
        for idx, r in enumerate(records, start=2):  # 資料從第 2 列
            if str(r.get("預約編號", "")) == str(booking_id):
                if r.get("櫃台審核") == "N":
                    return JSONResponse({"status": "error", "message": "此預約已被拒絕，無法修改"})
                sheet.update_cell(idx, 16, str(new_passengers))  # P 欄 = 16
                return JSONResponse({"status": "success", "message": "預約更新成功"})
        raise HTTPException(status_code=404, detail="找不到預約記錄")
    except Exception as e:
        print(f"[ERROR] 更新預約失敗: {e}")
        raise HTTPException(status_code=500, detail=f"更新失敗: {e}")

@app.post("/api/cancel-booking")
async def cancel_booking(cancel_data: Dict[str, Any]):
    """取消預約（C 欄改為 ❌ 已取消 Cancelled）"""
    try:
        sheet = get_sheet()
        if not sheet:
            raise HTTPException(status_code=500, detail="無法連接資料庫")

        booking_id = cancel_data.get("booking_id")
        if not booking_id:
            raise HTTPException(status_code=400, detail="缺少預約編號")

        records = sheet.get_all_records(head=2)
        for idx, r in enumerate(records, start=2):
            if str(r.get("預約編號", "")) == str(booking_id):
                sheet.update_cell(idx, 3, "❌ 已取消 Cancelled")  # C 欄 = 3
                return JSONResponse({"status": "success", "message": "預約取消成功"})
        raise HTTPException(status_code=404, detail="找不到預約記錄")
    except Exception as e:
        print(f"[ERROR] 取消預約失敗: {e}")
        raise HTTPException(status_code=500, detail=f"取消失敗: {e}")

@app.get("/health")
async def health_check():
    return {
        "status": "healthy",
        "service": "booking-manager",
        "timestamp": datetime.now().isoformat()
    }

@app.get("/")
async def root():
    return {
        "message": "飯店接駁車預約管理 API",
        "status": "running",
        "endpoints": [
            "POST /api/book",
            "POST /api/query-orders",
            "POST /api/update-booking",
            "POST /api/cancel-booking",
            "GET /health",
        ],
    }
