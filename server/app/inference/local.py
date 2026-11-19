import mimetypes
from pathlib import Path

import httpx

from .base import TryOnOutput


class LocalProvider:
    """调用本地 GPU 推理服务（inference/service.py）。"""

    name = "local"

    def __init__(self, base_url: str, timeout_seconds: float = 600.0) -> None:
        self._endpoint = f"{base_url.rstrip('/')}/generate"
        self._timeout = timeout_seconds

    async def generate(self, person_image: Path, garment_image: Path, cloth_type: str = "upper") -> TryOnOutput:
        person_type = mimetypes.guess_type(person_image.name)[0] or "image/png"
        garment_type = mimetypes.guess_type(garment_image.name)[0] or "image/png"

        async with httpx.AsyncClient(timeout=self._timeout) as client:
            with person_image.open("rb") as person_file, garment_image.open("rb") as garment_file:
                response = await client.post(
                    self._endpoint,
                    files={
                        "person": (person_image.name, person_file, person_type),
                        "garment": (garment_image.name, garment_file, garment_type),
                    },
                    data={"cloth_type": cloth_type},
                )

        if response.status_code != 200:
            detail = self._error_detail(response)
            if response.status_code == 400:
                # 输入校验失败，直接给用户看中文提示
                raise RuntimeError(detail)
            raise RuntimeError(f"推理服务返回 {response.status_code}: {detail}")

        media_type = response.headers.get("content-type", "image/png").split(";")[0]
        return TryOnOutput(data=response.content, media_type=media_type)

    @staticmethod
    def _error_detail(response: httpx.Response) -> str:
        try:
            payload = response.json()
        except ValueError:
            return response.text[:200]
        detail = payload.get("detail") if isinstance(payload, dict) else None
        if isinstance(detail, str) and detail:
            return detail
        return response.text[:200]
