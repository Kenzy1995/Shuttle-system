"""
快取管理模組
統一管理 Google Sheets 快取
"""
import logging
import sys
import os
from datetime import datetime
from threading import Lock
from typing import Any, Dict, List, Optional

# 添加父目錄到路徑
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config

logger = logging.getLogger("shuttle-api.cache")

# ========== 通用 Sheet 快取 ==========
SHEET_CACHE: Dict[str, Any] = {
    "values": None,
    "fetched_at": None,
    "sheet_name": None,
    "range_name": None,
}
CACHE_LOCK = Lock()


def get_cached_sheet_data(sheet_name: str, range_name: str) -> Optional[List[List[str]]]:
    """
    取得快取的 Sheet 資料
    
    Args:
        sheet_name: 工作表名稱
        range_name: 範圍名稱
        
    Returns:
        快取的資料，如果無效則返回 None
    """
    now = datetime.now()
    
    with CACHE_LOCK:
        cached_values = SHEET_CACHE.get("values")
        cached_sheet = SHEET_CACHE.get("sheet_name")
        cached_range = SHEET_CACHE.get("range_name")
        fetched_at = SHEET_CACHE.get("fetched_at")
        
        if (
            cached_values is not None
            and cached_sheet == sheet_name
            and cached_range == range_name
            and fetched_at is not None
            and (now - fetched_at).total_seconds() < config.CACHE_TTL_SECONDS
        ):
            return cached_values
        
        return None


def set_cached_sheet_data(sheet_name: str, range_name: str, values: List[List[str]]):
    """更新快取"""
    with CACHE_LOCK:
        SHEET_CACHE.update({
            "values": values,
            "fetched_at": datetime.now(),
            "sheet_name": sheet_name,
            "range_name": range_name,
        })


def invalidate_cache():
    """清除快取"""
    with CACHE_LOCK:
        SHEET_CACHE.update({
            "values": None,
            "fetched_at": None,
            "sheet_name": None,
            "range_name": None,
        })


# ========== 主表快取（帶 header_map）==========
MAIN_SHEET_CACHE: Dict[str, Any] = {
    "values": None,
    "header_map": None,
    "fetched_at": None,
}
MAIN_CACHE_LOCK = Lock()


def get_cached_main_sheet() -> Optional[tuple]:
    """
    取得快取的主表資料（包含 values 和 header_map）
    
    Returns:
        (values, header_map) 或 None
    """
    now = datetime.now()
    
    with MAIN_CACHE_LOCK:
        cached_values = MAIN_SHEET_CACHE.get("values")
        cached_header_map = MAIN_SHEET_CACHE.get("header_map")
        fetched_at = MAIN_SHEET_CACHE.get("fetched_at")
        
        if (
            cached_values is not None
            and cached_header_map is not None
            and fetched_at is not None
            and (now - fetched_at).total_seconds() < config.CACHE_TTL_SECONDS
        ):
            return cached_values, cached_header_map
        
        return None


def set_cached_main_sheet(values: List[List[str]], header_map: Dict[str, int]):
    """更新主表快取"""
    with MAIN_CACHE_LOCK:
        MAIN_SHEET_CACHE.update({
            "values": values,
            "header_map": header_map,
            "fetched_at": datetime.now(),
        })


def invalidate_main_cache():
    """清除主表快取"""
    with MAIN_CACHE_LOCK:
        MAIN_SHEET_CACHE.update({
            "values": None,
            "header_map": None,
            "fetched_at": None,
        })


# ========== 可預約班次表快取 ==========
CAP_SHEET_CACHE: Dict[str, Any] = {
    "values": None,
    "header_map": None,
    "hdr_row": None,
    "fetched_at": None,
}
CAP_CACHE_LOCK = Lock()


def get_cached_cap_sheet() -> Optional[tuple]:
    """
    取得快取的可預約班次表資料
    
    Returns:
        (values, header_map, hdr_row) 或 None
    """
    now = datetime.now()
    
    with CAP_CACHE_LOCK:
        cached_values = CAP_SHEET_CACHE.get("values")
        cached_header_map = CAP_SHEET_CACHE.get("header_map")
        cached_hdr_row = CAP_SHEET_CACHE.get("hdr_row")
        fetched_at = CAP_SHEET_CACHE.get("fetched_at")
        
        if (
            cached_values is not None
            and cached_header_map is not None
            and cached_hdr_row is not None
            and fetched_at is not None
            and (now - fetched_at).total_seconds() < config.CACHE_TTL_SECONDS
        ):
            return cached_values, cached_header_map, cached_hdr_row
        
        return None


def set_cached_cap_sheet(
    values: List[List[str]], header_map: Dict[str, int], hdr_row: int
):
    """更新可預約班次表快取"""
    with CAP_CACHE_LOCK:
        CAP_SHEET_CACHE.update({
            "values": values,
            "header_map": header_map,
            "hdr_row": hdr_row,
            "fetched_at": datetime.now(),
        })


def invalidate_cap_cache():
    """清除可預約班次表快取"""
    with CAP_CACHE_LOCK:
        CAP_SHEET_CACHE.update({
            "values": None,
            "header_map": None,
            "hdr_row": None,
            "fetched_at": None,
        })

