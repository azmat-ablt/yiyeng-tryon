from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, ConfigDict


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class AssetOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    url: str
    created_at: datetime


class TryOnCreate(BaseModel):
    person_id: str
    garment_id: str
    cloth_type: Literal["upper", "lower", "overall"] = "upper"


class JobOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    status: Literal["queued", "running", "succeeded", "failed"]
    result_url: str | None = None
    error: str | None = None
    created_at: datetime


class GarmentOut(BaseModel):
    """衣柜里的自有单品。"""

    model_config = ConfigDict(from_attributes=True)

    id: str
    url: str
    name: str
    cloth_type: Literal["upper", "lower", "overall"] = "upper"
    created_at: datetime


class ArchiveIn(BaseModel):
    """把一次试穿结果存入档案。"""

    result_url: str
    job_id: str | None = None
    person_url: str | None = None
    garment_name: str = "未命名单品"
    cloth_type: Literal["upper", "lower", "overall"] = "upper"
    cost_seconds: int | None = None


class ArchiveOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    result_url: str
    garment_name: str
    cloth_type: Literal["upper", "lower", "overall"] = "upper"
    person_url: str | None = None
    cost_seconds: int | None = None
    created_at: datetime
