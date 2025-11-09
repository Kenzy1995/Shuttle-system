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
from typing import Dict, Any
import re
import os


app = FastAPI(title="飯店接駁車預約管理 API")

# CORS 設定
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Google Sheets 設定
SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
SPREADSHEET_ID = "1xp54tKOczklmT8uacW-HMxwV8r0VOR2ui33jYcE2pUQ"
SHEET_NAME = "預約審核(櫃台)"

# 站點路線映射（循環路線）
STATION_ROUTE_MAP = {
    "福泰大飯店 Forte Hotel": 1,
    "南港展覽館-捷運3號出口 / Nangang Exhibition Center - MRT Exit 3": 2,
    "南港火車站 / Nangang Train Station": 3,
    "南港 LaLaport Shopping Park": 4
}

def get_credentials():
    """獲取 Google Sheets 憑證"""
    try:
        # 從環境變數讀取（Cloud Run 部署時使用）
        creds_env = os.getenv("GOOGLE_CREDENTIALS_JSON")
        if creds_env:
            creds_json = json.loads(creds_env)
        else:
            # 從本地檔案讀取（開發時使用）
            with open("credentials.json", "r") as f:
                creds_json = json.load(f)
        
        creds = Credentials.from_service_account_info(creds_json, scopes=SCOPES)
        return gspread.authorize(creds)
    except Exception as e:
        print(f"憑證初始化失敗: {e}")
        return None

def get_sheet():
    """獲取 Google Sheets 工作表"""
    try:
        client = get_credentials()
        if not client:
            return None
        return client.open_by_key(SPREADSHEET_ID).worksheet(SHEET_NAME)
    except Exception as e:
        print(f"獲取工作表失敗: {e}")
        return None

def generate_booking_id(sheet) -> str:
    """生成預約編號: YYMMDD + 3位序號"""
    try:
        # 獲取 A 欄的所有預約編號
        booking_ids = sheet.col_values(1)[1:]  # 跳過標題行
        
        # 過濾出今天的預約編號
        today_prefix = datetime.now().strftime('%y%m%d')
        today_bookings = [bid for bid in booking_ids if bid and bid.startswith(today_prefix)]
        
        # 計算今天的預約數量
        today_count = len(today_bookings)
        
        # 生成編號: YYMMDD + 3位序號
        booking_id = f"{today_prefix}{today_count + 1:03d}"
        return booking_id
    except Exception as e:
        print(f"生成預約編號失敗: {e}")
        # 如果失敗，使用時間戳作為備用
        return f"BK{int(datetime.now().timestamp())}"

def generate_qr_code(booking_data: Dict[str, Any]) -> tuple:
    """
    生成 QR Code 並返回 base64 圖片和原始資料
    返回: (base64_image, qr_data_json)
    """
    try:
        # QR Code 包含的資料
        qr_data = {
            "booking_id": booking_data.get("booking_id"),
            "name": booking_data.get("name"),
            "date": booking_data.get("date"),
            "time": booking_data.get("time"),
            "direction": booking_data.get("direction"),
            "pickup_station": booking_data.get("pickup_station"),
            "dropoff_station": booking_data.get("dropoff_station"),
            "passengers": booking_data.get("passengers"),
            "phone": booking_data.get("phone"),
            "email": booking_data.get("email"),
            "identity": booking_data.get("identity"),
            "timestamp": datetime.now().isoformat()
        }
        
        # 生成 QR Code 圖片
        qr = qrcode.QRCode(version=1, box_size=10, border=5)
        qr.add_data(json.dumps(qr_data, ensure_ascii=False))
        qr.make(fit=True)
        
        img = qr.make_image(fill_color="black", back_color="white")
        buffer = io.BytesIO()
        img.save(buffer, format="PNG")
        buffer.seek(0)
        
        img_str = base64.b64encode(buffer.read()).decode()
        base64_image = f"data:image/png;base64,{img_str}"
        
        return base64_image, json.dumps(qr_data, ensure_ascii=False)
        
    except Exception as e:
        print(f"生成 QR Code 失敗: {e}")
        return "", ""

def calculate_station_indexes(pickup_station: str, dropoff_station: str) -> tuple:
    """計算上車索引和下車索引（循環路線）"""
    try:
        # 獲取基本索引
        pickup_index = STATION_ROUTE_MAP.get(pickup_station, 0)
        dropoff_index = STATION_ROUTE_MAP.get(dropoff_station, 0)
        
        # 特殊處理：飯店有兩個索引
        if pickup_station == "福泰大飯店 Forte Hotel":
            # 如果是飯店上車，檢查下車站點來決定是去程還是回程
            if dropoff_station == "福泰大飯店 Forte Hotel":
                # 飯店到飯店（完整循環）
                pickup_index = 1
                dropoff_index = 5
            else:
                # 去程：飯店(1) 出發到其他站點
                pickup_index = 1
        
        elif dropoff_station == "福泰大飯店 Forte Hotel":
            # 回程：其他站點回到飯店(5)
            dropoff_index = 5
        
        return pickup_index, dropoff_index
        
    except Exception as e:
        print(f"計算站點索引失敗: {e}")
        return 0, 0

def calculate_route_range(pickup_index: int, dropoff_index: int) -> str:
    """計算涉及路段範圍（循環路線）"""
    try:
        if pickup_index == 0 or dropoff_index == 0:
            return ""
        
        # 處理循環路線
        if pickup_index < dropoff_index:
            # 正常順序：1→2→3→4→5
            route_range = list(range(pickup_index, dropoff_index + 1))
        else:
            # 跨越循環點（理論上不應該發生在正常預約中）
            route_range = list(range(pickup_index, 6)) + list(range(1, dropoff_index + 1))
        
        return ",".join(str(i) for i in route_range)
        
    except Exception as e:
        print(f"計算路段範圍失敗: {e}")
        return ""

def determine_direction(pickup_station: str, dropoff_station: str) -> str:
    """根據上下車站點判斷方向"""
    if pickup_station == "福泰大飯店 Forte Hotel":
        if dropoff_station == "福泰大飯店 Forte Hotel":
            return "循環"  # 飯店到飯店（完整循環）
        else:
            return "去程"  # 飯店出發到其他站點
    elif dropoff_station == "福泰大飯店 Forte Hotel":
        return "回程"  # 其他站點回到飯店
    else:
        # 站點之間的移動
        pickup_idx = STATION_ROUTE_MAP.get(pickup_station, 0)
        dropoff_idx = STATION_ROUTE_MAP.get(dropoff_station, 0)
        if pickup_idx < dropoff_idx:
            return "順向"
        else:
            return "逆向"

@app.post("/api/book")
async def submit_booking(booking_data: Dict[str, Any]):
    """提交新預約"""
    try:
        sheet = get_sheet()
        if not sheet:
            raise HTTPException(status_code=500, detail="無法連接資料庫")
        
        # 生成預約編號
        booking_id = generate_booking_id(sheet)
        
        # 獲取當前時間作為申請日期
        apply_date = datetime.now().strftime("%Y/%-m/%-d %H:%M")
        
        # 獲取上下車站點
        pickup_station = booking_data.get("pickLocation", "")
        dropoff_station = booking_data.get("dropLocation", "")
        
        # 判斷方向
        direction = determine_direction(pickup_station, dropoff_station)
        
        # 計算站點索引
        pickup_index, dropoff_index = calculate_station_indexes(pickup_station, dropoff_station)
        
        # 計算涉及路段範圍
        route_range = calculate_route_range(pickup_index, dropoff_index)
        
        # 生成 QR Code 圖片和資料
        qr_image, qr_data_str = generate_qr_code({
            "booking_id": booking_id,
            "name": booking_data.get("name", ""),
            "date": booking_data.get("date", ""),
            "time": booking_data.get("time", ""),
            "direction": direction,
            "pickup_station": pickup_station,
            "dropoff_station": dropoff_station,
            "passengers": booking_data.get("passengers", 1),
            "phone": booking_data.get("phone", ""),
            "email": booking_data.get("email", ""),
            "identity": booking_data.get("identity", "")
        })
        
        # 準備寫入資料（A-W 欄）
        row_data = [
            booking_id,                                   # A: 預約編號
            apply_date,                                   # B: 申請日期
            "✔️ 已預約 Booked",                          # C: 預約狀態
            booking_data.get("name", ""),                 # D: 姓名
            booking_data.get("phone", ""),                # E: 手機
            booking_data.get("email", ""),                # F: 信箱
            "住宿" if booking_data.get("identity") == "hotel" else "用餐",  # G: 身分
            booking_data.get("roomNumber", ""),           # H: 房號
            booking_data.get("checkIn", ""),              # I: 入住日期
            booking_data.get("checkOut", ""),             # J: 退房日期
            booking_data.get("diningDate", ""),           # K: 用餐日期
            direction,                                    # L: 往返（自動判斷）
            pickup_station,                               # M: 上車地點
            dropoff_station,                              # N: 下車地點
            f"{booking_data.get('date', '')} {booking_data.get('time', '')}",  # O: 車次
            str(booking_data.get("passengers", 1)),       # P: 預約人數
            str(pickup_index),                            # Q: 上車索引
            str(dropoff_index),                           # R: 下車索引
            route_range,                                  # S: 涉及路段範圍
            "",                                           # T: 確認人數（公式計算）
            "",                                           # U: 櫃台審核
            "",                                           # V: 備註
            qr_data_str                                   # W: QR資料
        ]
        
        # 寫入 Google Sheets
        sheet.append_row(row_data)
        
        # 生成完整的車票資料返回給前端
        ticket_data = {
            "booking_id": booking_id,
            "name": booking_data.get("name", ""),
            "phone": booking_data.get("phone", ""),
            "email": booking_data.get("email", ""),
            "date": booking_data.get("date", ""),
            "time": booking_data.get("time", ""),
            "direction": direction,
            "pickup_station": pickup_station,
            "dropoff_station": dropoff_station,
            "passengers": booking_data.get("passengers", 1),
            "identity": booking_data.get("identity", ""),
            "room_number": booking_data.get("roomNumber", ""),
            "check_in": booking_data.get("checkIn", ""),
            "check_out": booking_data.get("checkOut", ""),
            "dining_date": booking_data.get("diningDate", ""),
            "apply_date": apply_date,
            "pickup_index": pickup_index,
            "dropoff_index": dropoff_index,
            "route_range": route_range
        }
        
        return JSONResponse({
            "status": "success",
            "booking_id": booking_id,
            "qr_url": qr_image,
            "ticket_data": ticket_data,
            "message": "預約成功"
        })
        
    except Exception as e:
        print(f"預約提交失敗: {e}")
        raise HTTPException(status_code=500, detail=f"預約失敗: {str(e)}")

@app.post("/api/query-orders")
async def query_orders(query_data: Dict[str, Any]):
    """查詢個人預約記錄"""
    try:
        sheet = get_sheet()
        if not sheet:
            raise HTTPException(status_code=500, detail="無法連接資料庫")
        
        booking_id = query_data.get("booking_id", "").strip()
        phone = query_data.get("phone", "").strip()
        email = query_data.get("email", "").strip()
        
        # 檢查查詢條件
        if not any([booking_id, phone, email]):
            return JSONResponse({
                "status": "error",
                "message": "請提供預約編號、電話或信箱其中一項"
            })
        
        # 獲取所有記錄
        records = sheet.get_all_records(head=2)

        results = []
        
        for record in records:
            # 檢查匹配條件
            match_booking_id = booking_id and str(record.get("預約編號", "")).strip() == booking_id
            match_phone = phone and str(record.get("手機", "")).strip() == phone
            match_email = email and str(record.get("信箱", "")).strip() == email
            
            if match_booking_id or match_phone or match_email:
                # 從 W欄 讀取 QR 資料重新生成 QR Code
                qr_data_str = record.get("QR資料", "") or record.get("qr_data", "")
                
                if qr_data_str:
                    try:
                        qr_data = json.loads(qr_data_str)
                        qr_image, _ = generate_qr_code(qr_data)
                    except:
                        # 如果無法解析，重新生成 QR Code
                        qr_data = {
                            "booking_id": record.get("預約編號", ""),
                            "name": record.get("姓名", ""),
                            "date": record.get("車次", "").split()[0] if record.get("車次") else "",
                            "time": record.get("車次", "").split()[1] if record.get("車次") and " " in record.get("車次", "") else record.get("車次", ""),
                            "direction": record.get("往返", ""),
                            "pickup_station": record.get("上車地點", ""),
                            "dropoff_station": record.get("下車地點", ""),
                            "passengers": record.get("確認人數") or record.get("預約人數", ""),
                            "phone": record.get("手機", ""),
                            "email": record.get("信箱", ""),
                            "identity": record.get("身分", "")
                        }
                        qr_image, _ = generate_qr_code(qr_data)
                else:
                    # 如果沒有 QR 資料，重新生成
                    qr_data = {
                        "booking_id": record.get("預約編號", ""),
                        "name": record.get("姓名", ""),
                        "date": record.get("車次", "").split()[0] if record.get("車次") else "",
                        "time": record.get("車次", "").split()[1] if record.get("車次") and " " in record.get("車次", "") else record.get("車次", ""),
                        "direction": record.get("往返", ""),
                        "pickup_station": record.get("上車地點", ""),
                        "dropoff_station": record.get("下車地點", ""),
                        "passengers": record.get("確認人數") or record.get("預約人數", ""),
                        "phone": record.get("手機", ""),
                        "email": record.get("信箱", ""),
                        "identity": record.get("身分", "")
                    }
                    qr_image, _ = generate_qr_code(qr_data)
                
                # 構建完整的車票資料
                ticket_data = {
                    "booking_id": record.get("預約編號", ""),
                    "name": record.get("姓名", ""),
                    "phone": record.get("手機", ""),
                    "email": record.get("信箱", ""),
                    "date": record.get("車次", "").split()[0] if record.get("車次") else "",
                    "time": record.get("車次", "").split()[1] if record.get("車次") and " " in record.get("車次", "") else record.get("車次", ""),
                    "direction": record.get("往返", ""),
                    "pickup_station": record.get("上車地點", ""),
                    "dropoff_station": record.get("下車地點", ""),
                    "passengers": record.get("確認人數") or record.get("預約人數", ""),
                    "identity": record.get("身分", ""),
                    "room_number": record.get("房號", ""),
                    "check_in": record.get("入住日期", ""),
                    "check_out": record.get("退房日期", ""),
                    "dining_date": record.get("用餐日期", ""),
                    "apply_date": record.get("申請日期", ""),
                    "status": record.get("預約狀態", ""),
                    "audit_status": record.get("櫃台審核", ""),
                    "notes": record.get("備註", "")
                }
                
                results.append({
                    "ticket_data": ticket_data,
                    "qr_code": qr_image,
                    "raw_record": record
                })
        
        return JSONResponse({
            "status": "success",
            "data": results
        })
        
    except Exception as e:
        print(f"查詢訂單失敗: {e}")
        raise HTTPException(status_code=500, detail=f"查詢失敗: {str(e)}")

@app.post("/api/update-booking")
async def update_booking(update_data: Dict[str, Any]):
    """修改預約人數"""
    try:
        sheet = get_sheet()
        if not sheet:
            raise HTTPException(status_code=500, detail="無法連接資料庫")
        
        booking_id = update_data.get("booking_id")
        new_passengers = update_data.get("passengers")
        
        if not booking_id or not new_passengers:
            raise HTTPException(status_code=400, detail="缺少必要參數")
        
        # 查找預約記錄
        records = sheet.get_all_records(head=2)

        for i, record in enumerate(records, start=2):  # 從第2行開始（跳過標題）
            if str(record.get("預約編號", "")) == str(booking_id):
                # 檢查是否被拒絕
                if record.get("櫃台審核") == "N":
                    return JSONResponse({
                        "status": "error",
                        "message": "此預約已被拒絕，無法修改"
                    })
                
                # 更新預約人數（P欄位）
                sheet.update_cell(i, 16, str(new_passengers))  # P欄是第16列
                
                return JSONResponse({
                    "status": "success",
                    "message": "預約更新成功"
                })
        
        raise HTTPException(status_code=404, detail="找不到預約記錄")
        
    except Exception as e:
        print(f"更新預約失敗: {e}")
        raise HTTPException(status_code=500, detail=f"更新失敗: {str(e)}")

@app.post("/api/cancel-booking")
async def cancel_booking(cancel_data: Dict[str, Any]):
    """取消預約"""
    try:
        sheet = get_sheet()
        if not sheet:
            raise HTTPException(status_code=500, detail="無法連接資料庫")
        
        booking_id = cancel_data.get("booking_id")
        
        if not booking_id:
            raise HTTPException(status_code=400, detail="缺少預約編號")
        
        # 查找預約記錄
        records = sheet.get_all_records(head=2)

        for i, record in enumerate(records, start=2):
            if str(record.get("預約編號", "")) == str(booking_id):
                # 更新預約狀態為取消
                sheet.update_cell(i, 3, "❌ 已取消 Cancelled")  # C欄是第3列
                
                return JSONResponse({
                    "status": "success",
                    "message": "預約取消成功"
                })
        
        raise HTTPException(status_code=404, detail="找不到預約記錄")
        
    except Exception as e:
        print(f"取消預約失敗: {e}")
        raise HTTPException(status_code=500, detail=f"取消失敗: {str(e)}")

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
            "GET /health"
        ]
    }


