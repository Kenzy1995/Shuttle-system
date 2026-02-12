"""
Firebase 管理模組
處理 Firebase Admin SDK 的初始化和操作
"""
import os
import logging
import firebase_admin
from firebase_admin import credentials, db
from typing import Optional

import sys
import os

# 添加父目錄到路徑
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config

logger = logging.getLogger("shuttle-api.firebase")

# Firebase 初始化狀態
_firebase_initialized = False


def init_firebase() -> bool:
    """
    初始化 Firebase Admin SDK
    
    Returns:
        bool: 初始化是否成功
    """
    global _firebase_initialized
    
    if _firebase_initialized:
        return True
    
    try:
        if not firebase_admin._apps:
            service_account_path = "service_account.json"
            if os.path.exists(service_account_path):
                cred = credentials.Certificate(service_account_path)
                logger.info("Firebase: Using service account file")
            else:
                cred = credentials.ApplicationDefault()
                logger.info("Firebase: Using ApplicationDefault credentials")
            
            db_url = config.FIREBASE_RTDB_URL
            if not db_url:
                db_url = f"https://{config.GOOGLE_CLOUD_PROJECT}-default-rtdb.asia-southeast1.firebasedatabase.app/"
                logger.warning(f"Firebase: FIREBASE_RTDB_URL not set, using default: {db_url}")
            else:
                logger.info(f"Firebase: Using FIREBASE_RTDB_URL from env: {db_url}")
            
            firebase_admin.initialize_app(cred, {"databaseURL": db_url})
            logger.info("Firebase: Initialization successful")
            
            # 自動初始化必要的路徑（如果不存在）
            ensure_firebase_paths()
            
        _firebase_initialized = True
        return True
    except Exception as e:
        logger.error(f"Firebase initialization failed: {type(e).__name__}: {str(e)}")
        return False


def ensure_firebase_paths():
    """確保 Firebase 必要的路徑存在（自動初始化）"""
    try:
        paths = ["/sheet_locks", "/booking_seq"]
        for path in paths:
            ref = db.reference(path)
            snapshot = ref.get()
            if snapshot is None:
                ref.set({})
                logger.info(f"Firebase: Initialized path {path}")
    except Exception as e:
        logger.warning(f"Firebase: Failed to ensure paths: {type(e).__name__}: {str(e)}")


def get_reference(path: str):
    """獲取 Firebase 引用"""
    if not _firebase_initialized:
        init_firebase()
    return db.reference(path)


def get_value(path: str, default=None):
    """獲取 Firebase 值"""
    try:
        ref = get_reference(path)
        value = ref.get()
        return value if value is not None else default
    except Exception as e:
        logger.error(f"Firebase get_value error at {path}: {e}")
        return default


def set_value(path: str, value):
    """設置 Firebase 值"""
    try:
        ref = get_reference(path)
        ref.set(value)
        return True
    except Exception as e:
        logger.error(f"Firebase set_value error at {path}: {e}")
        return False


def delete_path(path: str):
    """刪除 Firebase 路徑"""
    try:
        ref = get_reference(path)
        ref.delete()
        return True
    except Exception as e:
        logger.error(f"Firebase delete_path error at {path}: {e}")
        return False

