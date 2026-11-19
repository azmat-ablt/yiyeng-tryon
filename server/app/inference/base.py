from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


@dataclass
class TryOnOutput:
    data: bytes
    media_type: str = "image/png"


class TryOnProvider(Protocol):
    name: str

    async def generate(self, person_image: Path, garment_image: Path, cloth_type: str = "upper") -> TryOnOutput: ...
