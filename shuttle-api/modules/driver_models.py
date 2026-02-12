"""
司機端 Pydantic 模型定義
"""
from typing import List, Optional
from pydantic import BaseModel


class DriverTrip(BaseModel):
    trip_id: str   # 主班次時間原始字串（當 key）
    date: str      # YYYY-MM-DD
    time: str      # HH:MM
    total_pax: int


class DriverPassenger(BaseModel):
    trip_id: str
    station: str          # 站點名稱
    updown: str           # "上車" / "下車"
    booking_id: str
    name: str
    phone: str
    room: str
    pax: int
    status: str           # "已上車" or ""
    direction: Optional[str] = None  # 去程 / 回程
    qrcode: str


class DriverAllPassenger(BaseModel):
    booking_id: str
    main_datetime: str    # 主班次時間原始字串
    depart_time: str      # HH:mm
    name: str
    phone: str
    room: str
    pax: int
    ride_status: str
    direction: str
    hotel_go: str
    mrt: str
    train: str
    mall: str
    hotel_back: str


class DriverAllData(BaseModel):
    """整合所有資料的回傳格式：一次給前端 trips / trip_passengers / passenger_list"""
    trips: List[DriverTrip]
    trip_passengers: List[DriverPassenger]
    passenger_list: List[DriverAllPassenger]


class DriverCheckinRequest(BaseModel):
    qrcode: str  # FT:{booking_id}:{hash}


class DriverCheckinResponse(BaseModel):
    status: str
    message: str
    booking_id: Optional[str] = None
    name: Optional[str] = None
    pax: Optional[int] = None
    station: Optional[str] = None
    main_datetime: Optional[str] = None


class DriverLocation(BaseModel):
    lat: float
    lng: float
    timestamp: float
    trip_id: Optional[str] = None


class BookingIdRequest(BaseModel):
    booking_id: str


class TripStatusRequest(BaseModel):
    main_datetime: str  # 格式: YYYY/MM/DD HH:MM
    status: str         # 已發車 / 已結束


class QrInfoRequest(BaseModel):
    qrcode: str


class QrInfoResponse(BaseModel):
    booking_id: Optional[str]
    name: Optional[str]
    main_datetime: Optional[str]
    ride_status: Optional[str]
    station_up: Optional[str]
    station_down: Optional[str]


class GoogleTripStartRequest(BaseModel):
    main_datetime: str
    driver_role: Optional[str] = None
    stops: Optional[List[str]] = None  # 從APP傳遞的停靠站點列表


class GoogleTripStartResponse(BaseModel):
    trip_id: Optional[str] = None
    share_url: Optional[str] = None
    stops: Optional[List[dict]] = None


class GoogleTripCompleteRequest(BaseModel):
    trip_id: str
    driver_role: Optional[str] = None
    main_datetime: Optional[str] = None  # 主班次時間，格式: YYYY/MM/DD HH:MM


class SystemStatusRequest(BaseModel):
    enabled: bool


class UpdateStationRequest(BaseModel):
    trip_id: str
    current_station: str

