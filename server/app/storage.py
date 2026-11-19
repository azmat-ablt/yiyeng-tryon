import uuid
from pathlib import Path

from fastapi import HTTPException, UploadFile

ALLOWED_CONTENT_TYPES = {
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
}
RESULT_EXTENSIONS = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp"}
MAX_UPLOAD_BYTES = 10 * 1024 * 1024


class LocalStorage:
    """本地磁盘存储。上线时替换为对象存储（OSS/S3）即可，接口保持不变。"""

    def __init__(self, root: Path, public_base_url: str) -> None:
        self.root = root
        self.public_base_url = public_base_url.rstrip("/")
        self.uploads = root / "uploads"
        self.results = root / "results"
        self.uploads.mkdir(parents=True, exist_ok=True)
        self.results.mkdir(parents=True, exist_ok=True)

    async def save_upload(self, file: UploadFile, kind: str) -> tuple[str, Path]:
        if file.content_type not in ALLOWED_CONTENT_TYPES:
            raise HTTPException(status_code=415, detail="仅支持 JPEG/PNG/WebP 图片")

        data = await file.read(MAX_UPLOAD_BYTES + 1)
        if len(data) > MAX_UPLOAD_BYTES:
            raise HTTPException(status_code=413, detail="图片超过 10MB")
        if not data:
            raise HTTPException(status_code=400, detail="图片内容为空")

        asset_id = uuid.uuid4().hex
        folder = self.uploads / kind
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"{asset_id}{ALLOWED_CONTENT_TYPES[file.content_type]}"
        path.write_bytes(data)
        return asset_id, path

    def save_result(self, job_id: str, data: bytes, media_type: str) -> str:
        extension = RESULT_EXTENSIONS.get(media_type, ".png")
        path = self.results / f"{job_id}{extension}"
        path.write_bytes(data)
        return self.public_url(path)

    def public_url(self, path: Path) -> str:
        relative = path.relative_to(self.root).as_posix()
        return f"{self.public_base_url}/files/{relative}"

    def path_from_url(self, url: str) -> Path | None:
        """把 /files/xxx 的公开地址反解成磁盘路径，越界返回 None。"""
        marker = "/files/"
        index = url.find(marker)
        if index < 0:
            return None
        relative = url[index + len(marker) :]
        if not relative:
            return None
        root = self.root.resolve()
        try:
            path = (root / relative).resolve()
            path.relative_to(root)
        except (OSError, ValueError):
            return None
        return path

    def delete_url(self, url: str) -> bool:
        """删除 URL 对应的本地文件，返回是否真的删掉了。"""
        path = self.path_from_url(url)
        if path is None or not path.is_file():
            return False
        try:
            path.unlink()
        except OSError:
            return False
        return True
