"""
Google Sheets 管理模組
處理 Google Sheets 的讀寫操作
"""
import logging
from typing import Dict, List, Optional, Tuple
from threading import Lock

import google.auth
import gspread
from googleapiclient.discovery import build

import sys
import os

# 添加父目錄到路徑
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
from modules import cache

logger = logging.getLogger("shuttle-api.sheets")

# Google Sheets 客戶端緩存
_gc_cache: Optional[gspread.Client] = None
_gc_lock = Lock()

# Worksheet 對象緩存
_ws_cache: Dict[str, gspread.Worksheet] = {}
_ws_lock = Lock()


def get_gspread_client(readonly: bool = False) -> gspread.Client:
    """
    獲取 gspread 客戶端（帶緩存）
    
    Args:
        readonly: 是否只讀
        
    Returns:
        gspread.Client 實例
    """
    global _gc_cache
    
    scopes = config.SCOPES_READONLY if readonly else config.SCOPES_FULL
    
    with _gc_lock:
        if _gc_cache is None:
            credentials_obj, _ = google.auth.default(scopes=scopes)
            _gc_cache = gspread.authorize(credentials_obj)
        return _gc_cache


def open_worksheet(name: str) -> gspread.Worksheet:
    """
    打開工作表（帶緩存）
    
    Args:
        name: 工作表名稱
        
    Returns:
        gspread.Worksheet 實例
    """
    with _ws_lock:
        if name not in _ws_cache:
            gc = get_gspread_client(readonly=False)
            spreadsheet = gc.open_by_key(config.SPREADSHEET_ID)
            _ws_cache[name] = spreadsheet.worksheet(name)
        return _ws_cache[name]


def get_sheet_data_via_api(
    sheet_name: str, range_name: Optional[str] = None
) -> List[List[str]]:
    """
    通過 Google Sheets API 讀取資料（用於只讀操作）
    
    Args:
        sheet_name: 工作表名稱
        range_name: 範圍（A1 表示法），如果為 None 則使用默認範圍
        
    Returns:
        資料列表
    """
    if range_name is None:
        range_name = f"{sheet_name}!{config.DEFAULT_RANGE}"
    elif "!" not in range_name:
        range_name = f"{sheet_name}!{range_name}"
    
    # 檢查快取
    cached = cache.get_cached_sheet_data(sheet_name, range_name)
    if cached is not None:
        return cached
    
    try:
        credentials_obj, _ = google.auth.default(scopes=config.SCOPES_READONLY)
        service = build("sheets", "v4", credentials=credentials_obj)
        result = (
            service.spreadsheets()
            .values()
            .get(spreadsheetId=config.SPREADSHEET_ID, range=range_name)
            .execute()
        )
        values = result.get("values", [])
        
        # 更新快取
        cache.set_cached_sheet_data(sheet_name, range_name, values)
        
        return values
    except Exception as e:
        logger.error(f"Error reading sheet {sheet_name}: {e}")
        raise


def get_sheet_data_api(
    sheet_name: str, range_name: Optional[str] = None
) -> Tuple[List[List[str]], int]:
    """
    通過 Google Sheets API 讀取資料（返回狀態碼）
    
    Args:
        sheet_name: 工作表名稱
        range_name: 範圍（A1 表示法），如果為 None 則使用默認範圍
        
    Returns:
        (資料列表, 狀態碼)
    """
    try:
        values = get_sheet_data_via_api(sheet_name, range_name)
        return values, 200
    except Exception as e:
        logger.error(f"Error reading sheet {sheet_name}: {e}")
        return [], 500


def get_header_map(worksheet: gspread.Worksheet, header_row: int) -> Dict[str, int]:
    """
    獲取表頭映射（欄位名稱 -> 列索引，1-based）
    
    Args:
        worksheet: 工作表對象
        header_row: 表頭行號（1-based）
        
    Returns:
        表頭映射字典
    """
    try:
        headers = worksheet.row_values(header_row)
        return {h: i + 1 for i, h in enumerate(headers) if h}
    except Exception as e:
        logger.error(f"Error getting header map: {e}")
        return {}


def get_sheet_headers(worksheet: gspread.Worksheet, header_row: int) -> List[str]:
    """
    獲取表頭列表
    
    Args:
        worksheet: 工作表對象
        header_row: 表頭行號（1-based）
        
    Returns:
        表頭列表
    """
    try:
        return worksheet.row_values(header_row)
    except Exception as e:
        logger.error(f"Error getting headers: {e}")
        return []


def get_main_sheet_data() -> Tuple[List[List[str]], Dict[str, int]]:
    """
    獲取主表資料（帶快取）
    
    Returns:
        (values, header_map) 元組
    """
    # 檢查快取
    cached = cache.get_cached_main_sheet()
    if cached is not None:
        return cached
    
    try:
        ws = open_worksheet(config.SHEET_NAME_MAIN)
        hmap = get_header_map(ws, config.HEADER_ROW_MAIN)
        headers = get_sheet_headers(ws, config.HEADER_ROW_MAIN)
        
        # 讀取所有資料
        all_values = ws.get_all_values()
        
        # 更新快取
        cache.set_cached_main_sheet(all_values, hmap)
        
        return all_values, hmap
    except Exception as e:
        logger.error(f"Error getting main sheet data: {e}")
        raise


def get_cap_sheet_data() -> Tuple[List[List[str]], Dict[str, int], int]:
    """
    獲取可預約班次表資料（帶快取）
    
    Returns:
        (values, header_map, header_row) 元組
    """
    # 檢查快取
    cached = cache.get_cached_cap_sheet()
    if cached is not None:
        return cached
    
    try:
        ws = open_worksheet(config.SHEET_NAME_CAP)
        
        # 找到表頭行（通常是第一行或第二行）
        hdr_row = 1
        headers = get_sheet_headers(ws, hdr_row)
        
        # 如果第一行不是有效的表頭，嘗試第二行
        if not headers or len(headers) < 3:
            hdr_row = 2
            headers = get_sheet_headers(ws, hdr_row)
        
        hmap = get_header_map(ws, hdr_row)
        all_values = ws.get_all_values()
        
        # 更新快取
        cache.set_cached_cap_sheet(all_values, hmap, hdr_row)
        
        return all_values, hmap, hdr_row
    except Exception as e:
        logger.error(f"Error getting cap sheet data: {e}")
        raise


def invalidate_sheet_cache():
    """清除所有 Sheet 快取"""
    cache.invalidate_cache()
    cache.invalidate_main_cache()
    cache.invalidate_cap_cache()
    logger.info("Sheet cache invalidated")

