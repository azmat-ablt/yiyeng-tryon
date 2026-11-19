from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from .api.routes import router
from .config import Settings
from .inference.registry import build_provider
from .jobs import JobManager
from .library import Library
from .storage import LocalStorage
from .store import Asset, AssetStore

settings = Settings()
storage = LocalStorage(settings.data_dir, settings.public_base_url)
library = Library(storage.root / "library.json")

# 启动时把衣柜里的单品重新灌进内存索引，避免重启后 garment_id 失效
assets = AssetStore()
for record in library.garments():
    path = storage.path_from_url(record.url)
    if path is None or not path.is_file():
        continue
    assets.add_garment(
        Asset(id=record.id, path=path, url=record.url, created_at=record.created_at)
    )

app = FastAPI(title="虚拟试衣 API")
app.state.storage = storage
app.state.assets = assets
app.state.library = library
app.state.jobs = JobManager(storage, build_provider(settings))

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/files", StaticFiles(directory=storage.root), name="files")
app.include_router(router)
