from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from .schemas import utcnow


@dataclass
class Asset:
    id: str
    path: Path
    url: str
    created_at: datetime = field(default_factory=utcnow)


class AssetStore:
    """内存索引。生产环境换成数据库（PostgreSQL），字段保持一致。"""

    def __init__(self) -> None:
        self._photos: dict[str, Asset] = {}
        self._garments: dict[str, Asset] = {}

    def add_photo(self, asset: Asset) -> Asset:
        self._photos[asset.id] = asset
        return asset

    def add_garment(self, asset: Asset) -> Asset:
        self._garments[asset.id] = asset
        return asset

    def get_photo(self, asset_id: str) -> Asset | None:
        return self._photos.get(asset_id)

    def get_garment(self, asset_id: str) -> Asset | None:
        return self._garments.get(asset_id)

    def remove_garment(self, asset_id: str) -> None:
        self._garments.pop(asset_id, None)
