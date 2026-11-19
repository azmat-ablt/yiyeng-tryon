from pathlib import Path

from .base import TryOnOutput


class RemoteProvider:
    """第三方推理 API 占位。选定供应商后在此实现上传与轮询逻辑。"""

    name = "remote"

    def __init__(self, api_url: str, api_key: str) -> None:
        self._api_url = api_url
        self._api_key = api_key

    async def generate(self, person_image: Path, garment_image: Path, cloth_type: str = "upper") -> TryOnOutput:
        if not self._api_url:
            raise RuntimeError("未配置 VTON_REMOTE_API_URL")
        raise NotImplementedError("请按选定的第三方 API（Replicate / fal / 国内云）实现")
