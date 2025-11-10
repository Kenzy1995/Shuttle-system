from __future__ import annotations
import io
import os
import time
import json
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional
import urllib.parse

import qrcode
from fastapi import FastAPI, HTTPException, Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, validator
import gspread
import google.auth


# ---------- 常數 ----------
SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive"
]
SPREADSHEET_ID = "1xp54tKOczklmT8uacW-HMxwV8r0VOR2ui33jYcE2pUQ"
SHEET_NAME = "工作表21"
BASE_URL = "https://booking-manager-995728097341.asia-east1.run.app"


ROUTE_ORDER = [
    "福泰大飯店",
    "南港展覽館-捷運3號出口",
    "南港火車站",
    "南港 LaLaport Shopping Park",
    "福泰大飯店",
]


# ---------- 工具 ----------
def _tz_now_str() -> str:
    os.environ.setdefault("TZ", "Asia/Taipei")
    try:
        time.tzset()
    except Exception:
        pass
    t = time.localtime()
    return f"{t.tm_year}/{t.tm_mon}/{t.tm_mday} {t.tm_hour:02d}:{t.tm_min:02d}"


def _time_hm_from_any(s: str) -> str:
    s = (s or "").strip().replace("：", ":")
    if " " in s and ":" in s:
        return s.split()[-1][:5]
    if ":" in s:
        return s[:5]
    return s


def _display_trip_str(date_iso: str, time_hm: str) -> str:
    y, m, d = date_iso.split("-")
    return f"'%s/%s %s" % (int(m), int(d), time_hm)


def _mmdd_prefix(date_iso: str) -> str:
    y, m, d = date_iso.split("-")
    return f"{int(m):02d}{int(d):02d}"


def _normalize_stop(name: str) -> str:
    mapping = {
        "福泰大飯店": {"福泰大飯店", "Forte Hotel"},
        "南港展覽館-捷運3號出口": {"南港展覽館-捷運3號出口", "南港展覽館捷運站"},
        "南港火車站": {"南港火車站"},
        "南港 LaLaport Shopping Park": {"南港 LaLaport Shopping Park", "LaLaport"},
    }
    raw = (name or "").strip()
    for key, aliases in mapping.items():
        if raw in aliases or raw.lower() in [a.lower() for a in aliases]:
            return key
    return raw


def _compute_indices_and_segments(direction: str, pickup: str, dropoff: str):
    norm_pick = _normalize_stop(pickup)
    norm_drop = _normalize_stop(dropoff)

    def base_index(stop: str) -> int:
        for i, s in enumerate(ROUTE_ORDER, start=1):
            if stop == s:
                return i
        return 0

    pick_idx = base_index(norm_pick)
    drop_idx = base_index(norm_drop)

    if norm_pick == "福泰大飯店" and direction == "去程":
        pick_idx = 1
    if norm_drop == "福泰大飯店" and direction == "回程":
        drop_idx = 5

    lo, hi = min(pick_idx, drop_idx), max(pick_idx, drop_idx)
    segs = [str(i) for i in range(lo, hi)]
    return pick_idx, drop_idx, ",".join(segs)


# ---------- Google Sheets ----------
def open_sheet() -> gspread.Worksheet:
    """開啟 Google Sheet 並添加詳細除錯資訊"""
    try:
        print("🔍 [DEBUG] 開始連接 Google Sheets...")
        
        # 1. 獲取憑證
        print("🔍 [DEBUG] 獲取 Google 憑證...")
        credentials, project = google.auth.default(scopes=SCOPES)
        print(f"🔍 [DEBUG] 憑證項目: {project}")
        
        # 2. 授權 gspread
        print("🔍 [DEBUG] 授權 gspread...")
        gc = gspread.authorize(credentials)
        print("✅ [DEBUG] gspread 授權成功")
        
        # 3. 開啟 Spreadsheet
        print(f"🔍 [DEBUG] 開啟 Spreadsheet ID: {SPREADSHEET_ID}")
        sh = gc.open_by_key(SPREADSHEET_ID)
        print(f"✅ [DEBUG] Spreadsheet 開啟成功: {sh.title}")
        
        # 4. 列出所有工作表
        worksheets = sh.worksheets()
        worksheet_names = [ws.title for ws in worksheets]
        print(f"📋 [DEBUG] 所有工作表: {worksheet_names}")
        
        # 5. 檢查目標工作表是否存在
        if SHEET_NAME not in worksheet_names:
            print(f"❌ [DEBUG] 錯誤: 找不到工作表 '{SHEET_NAME}'")
            print(f"📋 [DEBUG] 現有工作表: {worksheet_names}")
            raise RuntimeError(f"找不到工作表: {SHEET_NAME}")
        
        # 6. 開啟目標工作表
        print(f"🔍 [DEBUG] 開啟工作表: {SHEET_NAME}")
        ws = sh.worksheet(SHEET_NAME)
        print(f"✅ [DEBUG] 工作表開啟成功: {ws.title}")
        
        # 7. 讀取表頭確認結構
        headers = ws.row_values(1)
        print(f"📋 [DEBUG] 工作表表頭: {headers}")
        print(f"📊 [DEBUG] 現有資料行數: {len(ws.get_all_values())}")
        
        return ws
        
    except Exception as e:
        print(f"❌ [DEBUG] 連接失敗: {str(e)}")
        print(f"❌ [DEBUG] 錯誤類型: {type(e).__name__}")
        raise RuntimeError(f"無法開啟 Google Sheet: {str(e)}")


def _read_headers(ws: gspread.Worksheet) -> List[str]:
    """讀取表頭並除錯"""
    try:
        headers = ws.row_values(1)
        cleaned_headers = [h.strip() for h in headers if h.strip()]
        print(f"📋 [DEBUG] 讀取到表頭: {cleaned_headers}")
        return cleaned_headers
    except Exception as e:
        print(f"❌ [DEBUG] 讀取表頭失敗: {str(e)}")
        return []


def _read_all_rows(ws: gspread.Worksheet) -> List[List[str]]:
    """讀取所有資料行"""
    try:
        rows = ws.get_all_values()
        print(f"📊 [DEBUG] 讀取到 {len(rows)} 行資料")
        return rows
    except Exception as e:
        print(f"❌ [DEBUG] 讀取資料失敗: {str(e)}")
        return []


def _find_rows_by_pred(ws: gspread.Worksheet, pred) -> List[int]:
    values = _read_all_rows(ws)
    if not values:
        return []
    headers = values[0]
    result = []
    for i, row in enumerate(values[1:], start=2):
        d = {headers[j]: row[j] if j < len(row) else "" for j in range(len(headers))}
        if pred(d):
            result.append(i)
    return result


def _get_max_seq_for_date(ws: gspread.Worksheet, date_iso: str) -> int:
    """獲取指定日期的最大序號"""
    try:
        headers = _read_headers(ws)
        all_values = _read_all_rows(ws)
        
        if not all_values:
            print("📊 [DEBUG] 沒有找到任何資料")
            return 0
            
        if "預約編號" not in headers:
            print(f"❌ [DEBUG] 錯誤: 表頭中找不到 '預約編號'")
            print(f"📋 [DEBUG] 現有表頭: {headers}")
            return 0
            
        idx = headers.index("預約編號")
        prefix = _mmdd_prefix(date_iso)
        max_seq = 0
        
        print(f"🔍 [DEBUG] 尋找日期 {date_iso} 的預約編號 (前綴: {prefix})")
        
        for row_num, row in enumerate(all_values[1:], start=2):
            if len(row) <= idx:
                continue
            booking = row[idx]
            if booking and booking.startswith(prefix):
                try:
                    seq = int(booking[len(prefix):])
                    max_seq = max(max_seq, seq)
                    print(f"📝 [DEBUG] 找到預約編號: {booking}, 序號: {seq}")
                except Exception as e:
                    print(f"⚠️ [DEBUG] 解析預約編號失敗: {booking}, 錯誤: {e}")
                    
        print(f"📊 [DEBUG] 日期 {date_iso} 的最大序號: {max_seq}")
        return max_seq
        
    except Exception as e:
        print(f"❌ [DEBUG] 獲取最大序號失敗: {str(e)}")
        return 0


# ---------- Pydantic ----------
class BookPayload(BaseModel):
    direction: str
    date: str
    station: str
    time: str
    identity: str
    checkIn: Optional[str] = None
    checkOut: Optional[str] = None
    diningDate: Optional[str] = None
    roomNumber: Optional[str] = None
    name: str
    phone: str
    email: str
    passengers: int = Field(..., ge=1, le=4)
    pickLocation: str
    dropLocation: str

    @validator("direction")
    def _v_dir(cls, v):
        if v not in {"去程", "回程"}:
            raise ValueError("方向僅允許 去程 / 回程")
        return v


class QueryPayload(BaseModel):
    booking_id: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None


class ModifyPayload(BaseModel):
    booking_id: str
    direction: Optional[str] = None
    date: Optional[str] = None
    station: Optional[str] = None
    time: Optional[str] = None
    passengers: Optional[int] = Field(None, ge=1, le=4)
    pickLocation: Optional[str] = None
    dropLocation: Optional[str] = None


class DeletePayload(BaseModel):
    booking_id: str


class CheckInPayload(BaseModel):
    code: Optional[str] = None
    booking_id: Optional[str] = None


class OpsRequest(BaseModel):
    action: str
    data: Dict[str, Any]


# ---------- FastAPI ----------
app = FastAPI(title="Shuttle Ops API", version="1.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://hotel-web-995728097341.asia-east1.run.app",
        "http://127.0.0.1:8080",
        "http://localhost:8080",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health():
    return {"status": "ok", "time": _tz_now_str()}


@app.get("/api/qr/{code}")
def qr_image(code: str):
    decoded_code = urllib.parse.unquote(code)
    img = qrcode.make(decoded_code)
    bio = io.BytesIO()
    img.save(bio, format="PNG")
    return Response(content=bio.getvalue(), media_type="image/png")


# ---------- 主 API ----------
@app.post("/api/ops")
def ops(req: OpsRequest):
    print(f"🎯 [DEBUG] 收到請求: action={req.action}, data={req.data}")
    
    action = req.action.lower().strip()
    data = req.data or {}
    
    try:
        # 開啟 Google Sheet
        print("🔍 [DEBUG] 開始開啟 Google Sheet...")
        ws = open_sheet()
        print("✅ [DEBUG] Google Sheet 開啟成功")
        
        headers = _read_headers(ws)
        print(f"📋 [DEBUG] 可用表頭: {headers}")

        # ===== 新增預約 =====
        if action == "book":
            print("📝 [DEBUG] 開始處理預約請求...")
            p = BookPayload(**data)
            print(f"📋 [DEBUG] 解析後的預約資料:")
            print(f"  - 方向: {p.direction}")
            print(f"  - 日期: {p.date}")
            print(f"  - 站點: {p.station}")
            print(f"  - 時間: {p.time}")
            print(f"  - 姓名: {p.name}")
            print(f"  - 電話: {p.phone}")
            print(f"  - 上車: {p.pickLocation}")
            print(f"  - 下車: {p.dropLocation}")
            print(f"  - 人數: {p.passengers}")
            
            # 生成預約編號
            last_seq = _get_max_seq_for_date(ws, p.date)
            booking_id = f"{_mmdd_prefix(p.date)}{last_seq + 1:03d}"
            print(f"🎫 [DEBUG] 生成預約編號: {booking_id}")
            
            car_display = _display_trip_str(p.date, _time_hm_from_any(p.time))
            pk_idx, dp_idx, seg_str = _compute_indices_and_segments(p.direction, p.pickLocation, p.dropLocation)
            qr_content = f"FORTEXZ:{booking_id}"
            qr_url = f"{BASE_URL}/api/qr/{urllib.parse.quote(qr_content)}"

            # 建立資料行
            row_data = {
                "預約編號": booking_id,
                "申請日期": _tz_now_str(),
                "預約狀態": "已預約",
                "姓名": p.name,
                "手機": p.phone,
                "信箱": p.email,
                "身分": "住宿貴賓" if p.identity == "hotel" else "用餐貴賓",
                "房號": p.roomNumber or "",
                "入住日期": p.checkIn or "",
                "退房日期": p.checkOut or "",
                "用餐日期": p.diningDate or "",
                "往返": p.direction,
                "上車地點": p.pickLocation,
                "下車地點": p.dropLocation,
                "車次": car_display,
                "預約人數": p.passengers,
                "上車索引": pk_idx,
                "下車索引": dp_idx,
                "涉及路段範圍": seg_str,
                "QR編碼": qr_content,
            }

            print(f"📊 [DEBUG] 準備寫入的資料:")
            for key, value in row_data.items():
                print(f"  - {key}: {value}")

            # 對齊表頭
            newrow = [row_data.get(h, "") for h in headers]
            print(f"📝 [DEBUG] 對齊表頭後的資料行: {newrow}")
            
            # 寫入資料
            print("💾 [DEBUG] 開始寫入 Google Sheet...")
            ws.append_row(newrow, value_input_option="USER_ENTERED")
            print("✅ [DEBUG] 資料寫入成功！")

            return {
                "status": "success", 
                "booking_id": booking_id, 
                "qr_url": qr_url, 
                "qr_content": qr_content
            }

        # ===== 查詢 =====
        elif action == "query":
            p = QueryPayload(**data)
            if not (p.booking_id or p.phone or p.email):
                raise HTTPException(400, "至少提供 booking_id / phone / email 其中一項")
            all_rows = _read_all_rows(ws)
            results = []
            hdrs = all_rows[0]
            now = datetime.now()
            for row in all_rows[1:]:
                rec = {hdrs[i]: row[i] if i < len(row) else "" for i in range(len(hdrs))}
                if p.booking_id and rec.get("預約編號") != p.booking_id:
                    continue
                if p.phone and rec.get("手機") != p.phone:
                    continue
                if p.email and rec.get("信箱") != p.email:
                    continue
                if rec.get("櫃台審核") == "n":
                    rec["預約狀態"] = "已拒絕"
                results.append(rec)
            return results

        # ===== 修改 =====
        elif action == "modify":
            p = ModifyPayload(**data)
            target = _find_rows_by_pred(ws, lambda r: r.get("預約編號") == p.booking_id)
            if not target:
                raise HTTPException(404, "找不到此預約編號")
            rowno = target[0]
            row_data = ws.row_values(rowno)
            headers = _read_headers(ws)
            row_map = {headers[i]: row_data[i] if i < len(row_data) else "" for i in range(len(headers))}

            if row_map.get("櫃台審核") == "n":
                raise HTTPException(403, "此預約已被櫃台拒絕，無法修改")

            ws.update_cell(rowno, headers.index("預約狀態") + 1, "已預約")
            ws.update_cell(rowno, headers.index("最後操作時間") + 1, f"{_tz_now_str()} 已修改")
            return {"status": "success", "booking_id": p.booking_id}

        # ===== 刪除 =====
        elif action == "delete":
            p = DeletePayload(**data)
            target = _find_rows_by_pred(ws, lambda r: r.get("預約編號") == p.booking_id)
            if not target:
                raise HTTPException(404, "找不到此預約編號")
            rowno = target[0]
            row_data = ws.row_values(rowno)
            headers = _read_headers(ws)
            row_map = {headers[i]: row_data[i] if i < len(row_data) else "" for i in range(len(headers))}

            if row_map.get("櫃台審核") == "n":
                raise HTTPException(403, "此預約已被櫃台拒絕，無法刪除")

            ws.update_cell(rowno, headers.index("預約狀態") + 1, "已刪除")
            ws.update_cell(rowno, headers.index("最後操作時間") + 1, f"{_tz_now_str()} 已刪除")
            return {"status": "success", "booking_id": p.booking_id}

        # ===== 掃碼上車 =====
        elif action == "check_in":
            p = CheckInPayload(**data)
            if not (p.code or p.booking_id):
                raise HTTPException(400, "需提供 code 或 booking_id")
            target = _find_rows_by_pred(ws, lambda r: r.get("QR編碼") == p.code or r.get("預約編號") == p.booking_id)
            if not target:
                raise HTTPException(404, "找不到符合條件之訂單")
            rowno = target[0]
            ws.update_cell(rowno, headers.index("乘車狀態") + 1, "已上車")
            ws.update_cell(rowno, headers.index("最後操作時間") + 1, f"{_tz_now_str()} 已上車")
            return {"status": "success", "row": rowno}

    else:
        raise HTTPException(400, f"未知 action：{action}")
            
    except HTTPException:
        raise
    except Exception as e:
        print(f"❌ [DEBUG] 伺服器錯誤: {str(e)}")
        import traceback
        print(f"❌ [DEBUG] 錯誤堆疊: {traceback.format_exc()}")
        raise HTTPException(500, f"伺服器錯誤: {str(e)}")


@app.get("/api/debug")
def debug_endpoint():
    """除錯端點，檢查 Google Sheet 連線"""
    try:
        print("🔍 [DEBUG] 測試 Google Sheet 連線...")
        ws = open_sheet()
        headers = _read_headers(ws)
        all_rows = _read_all_rows(ws)
        
        return {
            "status": "success",
            "sheet_title": ws.title,
            "headers": headers,
            "row_count": len(all_rows),
            "first_few_rows": all_rows[:3] if len(all_rows) > 3 else all_rows,
            "message": "Google Sheet 連線正常"
        }
    except Exception as e:
        return {
            "status": "error",
            "message": str(e),
            "error_type": type(e).__name__
        }


@app.get("/api/test-write")
def test_write():
    """測試寫入功能"""
    try:
        ws = open_sheet()
        test_data = ["測試資料", _tz_now_str(), "測試人員", "123456789"]
        ws.append_row(test_data, value_input_option="USER_ENTERED")
        return {"status": "success", "message": "測試寫入成功"}
    except Exception as e:
        return {"status": "error", "message": str(e)}
