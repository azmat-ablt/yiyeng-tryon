import mimetypes
from pathlib import Path

from .base import TryOnOutput


class StubProvider:
    """占位实现：直接回传人像，用于跑通上传 → 任务 → 展示的完整链路。"""

    name = "stub"

    async def generate(self, person_image: Path, garment_image: Path, cloth_type: str = "upper") -> TryOnOutput:
        media_type, _ = mimetypes.guess_type(person_image.name)
        return TryOnOutput(data=person_image.read_bytes(), media_type=media_type or "image/png")
