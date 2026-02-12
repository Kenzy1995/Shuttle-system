"""
通用工具函數模組
"""
import os
import time
import hashlib
from datetime import datetime, timedelta
from typing import Optional, Tuple

import sys
import os

# 添加父目錄到路徑
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config


def tz_now() -> datetime:
    """台北時間 now（作為時間比較用）"""
    os.environ.setdefault("TZ", "Asia/Taipei")
    try:
        time.tzset()
    except Exception:
        pass
    return datetime.now()


def tz_now_str() -> str:
    """台北時間 now 的字串（寫回表格用）"""
    t = tz_now()
    return t.strftime("%Y-%m-%d %H:%M:%S")


def today_iso_taipei() -> str:
    """取得今天的 ISO 格式日期（YYYY-MM-DD）"""
    os.environ.setdefault("TZ", "Asia/Taipei")
    try:
        time.tzset()
    except Exception:
        pass
    t = time.localtime()
    return f"{t.tm_year:04d}-{t.tm_mon:02d}-{t.tm_mday:02d}"


def time_hm_from_any(s: str) -> str:
    """從各種時間格式中提取 HH:MM"""
    s = (s or "").strip().replace("：", ":")
    if " " in s and ":" in s:
        return s.split()[-1][:5]
    if ":" in s:
        return s[:5]
    return s


def display_trip_str(date_iso: str, time_hm: str) -> str:
    """格式化車次顯示字串（例如：12/24 18:30）"""
    if not date_iso or not time_hm:
        return ""
    try:
        y, m, d = date_iso.split("-")
        return f"{int(m)}/{int(d)} {time_hm}"
    except Exception:
        return ""


def compute_indices_and_segments(pickup: str, dropoff: str) -> Tuple[int, int, str]:
    """計算上車索引、下車索引和涉及路段範圍"""
    ps = (pickup or "").strip()
    ds = (dropoff or "").strip()
    pick_idx = config.PICK_INDEX_MAP_EXACT.get(ps, 0)
    drop_idx = config.DROP_INDEX_MAP_EXACT.get(ds, 0)
    if pick_idx == 0 or drop_idx == 0 or drop_idx <= pick_idx:
        return pick_idx, drop_idx, ""
    segs = list(range(pick_idx, drop_idx))
    seg_str = ",".join(str(i) for i in segs)
    return pick_idx, drop_idx, seg_str


def compute_main_departure_datetime(
    direction: str, pickup: str, date_iso: str, time_hm: str
) -> str:
    """計算主班次時間"""
    date_iso = (date_iso or "").strip()
    time_hm = time_hm_from_any(time_hm or "")
    if not date_iso or not time_hm:
        return ""

    try:
        dt = datetime.strptime(f"{date_iso} {time_hm}", "%Y-%m-%d %H:%M")
    except Exception:
        return ""

    if direction != "回程":
        return dt.strftime("%Y/%m/%d %H:%M")

    p = (pickup or "").strip()
    offset_min = 0

    if "捷運" in p or "Exhibition Center" in p:
        offset_min = 5
    elif "火車" in p or "Train Station" in p:
        offset_min = 10
    elif "LaLaport" in p:
        offset_min = 20

    if offset_min:
        dt = dt - timedelta(minutes=offset_min)

    return dt.strftime("%Y/%m/%d %H:%M")


def normalize_station_for_capacity(direction: str, pick: str, drop: str) -> str:
    """正規化站點名稱（用於容量檢查）"""
    return (drop if direction == "去程" else pick).strip()


def email_hash6(email: str) -> str:
    """生成 Email 的 6 位雜湊值"""
    return hashlib.sha256((email or "").encode("utf-8")).hexdigest()[:6]


def safe_int(v, default: int = 0) -> int:
    """安全轉 int，用在確認人數／人數欄位"""
    try:
        s = str(v).strip()
        if not s:
            return default
        return int(float(s))
    except Exception:
        return default

