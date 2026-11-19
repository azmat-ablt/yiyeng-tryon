"""衣橱与档案的本地索引。

落盘为 JSON（data/library.json），这样「删除」可以同时清掉磁盘上的图片：
索引里存着图片 URL，删除时由 LocalStorage 反解出文件路径并 unlink。

生产环境换成数据库即可，对外接口保持不变。
"""

from __future__ import annotations

import json
import threading
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path

from .schemas import utcnow

ClothType = str  # upper | lower | overall


@dataclass
class GarmentRecord:
    id: str
    url: str
    name: str
    cloth_type: ClothType = "upper"
    created_at: datetime = field(default_factory=utcnow)


@dataclass
class ArchiveRecord:
    id: str
    result_url: str
    garment_name: str
    cloth_type: ClothType = "upper"
    person_url: str | None = None
    cost_seconds: int | None = None
    created_at: datetime = field(default_factory=utcnow)


def _parse_time(value: object) -> datetime:
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            pass
    return utcnow()


class Library:
    """衣橱（自有单品）与档案（已试穿结果）的 JSON 索引。"""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = threading.Lock()
        self._garments: list[GarmentRecord] = []
        self._archive: list[ArchiveRecord] = []
        self._load()

    # ---------- 读写 ----------
    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return

        for item in raw.get("garments", []):
            if not isinstance(item, dict) or not item.get("url"):
                continue
            self._garments.append(
                GarmentRecord(
                    id=str(item.get("id", "")),
                    url=str(item["url"]),
                    name=str(item.get("name") or "未命名单品"),
                    cloth_type=str(item.get("cloth_type") or "upper"),
                    created_at=_parse_time(item.get("created_at")),
                )
            )

        for item in raw.get("archive", []):
            if not isinstance(item, dict) or not item.get("result_url"):
                continue
            self._archive.append(
                ArchiveRecord(
                    id=str(item.get("id", "")),
                    result_url=str(item["result_url"]),
                    garment_name=str(item.get("garment_name") or "未命名单品"),
                    cloth_type=str(item.get("cloth_type") or "upper"),
                    person_url=item.get("person_url") or None,
                    cost_seconds=item.get("cost_seconds"),
                    created_at=_parse_time(item.get("created_at")),
                )
            )

        self._garments.sort(key=lambda r: r.created_at, reverse=True)
        self._archive.sort(key=lambda r: r.created_at, reverse=True)

    def _flush(self) -> None:
        payload = {
            "garments": [
                {**asdict(record), "created_at": record.created_at.isoformat()}
                for record in self._garments
            ],
            "archive": [
                {**asdict(record), "created_at": record.created_at.isoformat()}
                for record in self._archive
            ],
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(self.path)

    # ---------- 衣橱 ----------
    def garments(self) -> list[GarmentRecord]:
        with self._lock:
            return list(self._garments)

    def get_garment(self, garment_id: str) -> GarmentRecord | None:
        with self._lock:
            return next((item for item in self._garments if item.id == garment_id), None)

    def add_garment(self, record: GarmentRecord) -> GarmentRecord:
        with self._lock:
            self._garments = [item for item in self._garments if item.id != record.id]
            self._garments.insert(0, record)
            self._flush()
        return record

    def remove_garment(self, garment_id: str) -> GarmentRecord | None:
        with self._lock:
            target = next((item for item in self._garments if item.id == garment_id), None)
            if target is None:
                return None
            self._garments = [item for item in self._garments if item.id != garment_id]
            self._flush()
        return target

    # ---------- 档案 ----------
    def archive(self) -> list[ArchiveRecord]:
        with self._lock:
            return list(self._archive)

    def add_archive(self, record: ArchiveRecord) -> ArchiveRecord:
        with self._lock:
            self._archive = [item for item in self._archive if item.id != record.id]
            self._archive.insert(0, record)
            self._flush()
        return record

    def remove_archive(self, archive_id: str) -> ArchiveRecord | None:
        with self._lock:
            target = next((item for item in self._archive if item.id == archive_id), None)
            if target is None:
                return None
            self._archive = [item for item in self._archive if item.id != archive_id]
            self._flush()
        return target
