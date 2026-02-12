"""
Pydantic 模型定義
用於 API 請求驗證
"""
from typing import Optional
from pydantic import BaseModel, Field, validator


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
    lang: str = Field("zh", pattern="^(zh|en|ja|ko)$")

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
    phone: Optional[str] = None
    email: Optional[str] = None
    lang: str = Field("zh", pattern="^(zh|en|ja|ko)$")


class DeletePayload(BaseModel):
    booking_id: str
    lang: str = Field("zh", pattern="^(zh|en|ja|ko)$")


class CheckInPayload(BaseModel):
    code: Optional[str] = None
    booking_id: Optional[str] = None


class MailPayload(BaseModel):
    booking_id: str
    lang: str = Field("zh", pattern="^(zh|en|ja|ko)$")
    kind: str = Field(..., pattern="^(book|modify|cancel)$")
    ticket_png_base64: Optional[str] = None


class OpsRequest(BaseModel):
    action: str
    data: dict

