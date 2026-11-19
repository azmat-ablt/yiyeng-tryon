import uuid

from fastapi import APIRouter, Depends, File, Form, HTTPException, Response, UploadFile

from ..deps import get_asset_store, get_job_manager, get_library, get_storage
from ..jobs import JobManager
from ..library import ArchiveRecord, GarmentRecord, Library
from ..schemas import ArchiveIn, ArchiveOut, AssetOut, GarmentOut, JobOut, TryOnCreate
from ..storage import LocalStorage
from ..store import Asset, AssetStore

router = APIRouter(prefix="/api")

CLOTH_TYPES = {"upper", "lower", "overall"}


def _cloth_type(value: str | None) -> str:
    return value if value in CLOTH_TYPES else "upper"


@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@router.post("/photos", response_model=AssetOut, status_code=201)
async def upload_photo(
    file: UploadFile = File(...),
    storage: LocalStorage = Depends(get_storage),
    assets: AssetStore = Depends(get_asset_store),
) -> AssetOut:
    asset_id, path = await storage.save_upload(file, "photos")
    asset = Asset(id=asset_id, path=path, url=storage.public_url(path))
    return AssetOut.model_validate(assets.add_photo(asset))


@router.post("/garments", response_model=AssetOut, status_code=201)
async def upload_garment(
    file: UploadFile = File(...),
    name: str | None = Form(None),
    cloth_type: str = Form("upper"),
    save: bool = Form(False),
    storage: LocalStorage = Depends(get_storage),
    assets: AssetStore = Depends(get_asset_store),
    library: Library = Depends(get_library),
) -> AssetOut:
    """上传衣物。save=true 时同时收进衣柜，否则只当作一次性素材（如精选单品）。"""
    asset_id, path = await storage.save_upload(file, "garments")
    asset = Asset(id=asset_id, path=path, url=storage.public_url(path))
    assets.add_garment(asset)

    if save:
        display_name = (name or file.filename or "未命名单品").strip()[:60] or "未命名单品"
        library.add_garment(
            GarmentRecord(
                id=asset.id,
                url=asset.url,
                name=display_name,
                cloth_type=_cloth_type(cloth_type),
                created_at=asset.created_at,
            )
        )

    return AssetOut.model_validate(asset)


@router.get("/garments", response_model=list[GarmentOut])
async def list_garments(library: Library = Depends(get_library)) -> list[GarmentOut]:
    return [GarmentOut.model_validate(item) for item in library.garments()]


@router.delete("/garments/{garment_id}", status_code=204)
async def delete_garment(
    garment_id: str,
    storage: LocalStorage = Depends(get_storage),
    assets: AssetStore = Depends(get_asset_store),
    library: Library = Depends(get_library),
) -> Response:
    """从衣柜删除：索引记录和磁盘上的原图一起删掉。"""
    record = library.remove_garment(garment_id)
    if record is None:
        raise HTTPException(status_code=404, detail="衣柜里没有这件单品")

    storage.delete_url(record.url)
    assets.remove_garment(garment_id)
    return Response(status_code=204)


@router.post("/tryon", response_model=JobOut, status_code=202)
async def create_tryon(
    payload: TryOnCreate,
    assets: AssetStore = Depends(get_asset_store),
    jobs: JobManager = Depends(get_job_manager),
) -> JobOut:
    person = assets.get_photo(payload.person_id)
    if person is None:
        raise HTTPException(status_code=404, detail="人像不存在")

    garment = assets.get_garment(payload.garment_id)
    if garment is None:
        raise HTTPException(status_code=404, detail="衣物不存在")

    return JobOut.model_validate(jobs.create(person, garment, payload.cloth_type))


@router.get("/jobs/{job_id}", response_model=JobOut)
async def get_job(job_id: str, jobs: JobManager = Depends(get_job_manager)) -> JobOut:
    job = jobs.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="任务不存在")
    return JobOut.model_validate(job)


@router.get("/archive", response_model=list[ArchiveOut])
async def list_archive(library: Library = Depends(get_library)) -> list[ArchiveOut]:
    return [ArchiveOut.model_validate(item) for item in library.archive()]


@router.post("/archive", response_model=ArchiveOut, status_code=201)
async def save_archive(payload: ArchiveIn, library: Library = Depends(get_library)) -> ArchiveOut:
    """把一次成功的试穿存进档案（同一任务重复提交会覆盖而不是堆叠）。"""
    record = ArchiveRecord(
        id=payload.job_id or uuid.uuid4().hex,
        result_url=payload.result_url,
        garment_name=payload.garment_name.strip()[:60] or "未命名单品",
        cloth_type=_cloth_type(payload.cloth_type),
        person_url=payload.person_url,
        cost_seconds=payload.cost_seconds,
    )
    return ArchiveOut.model_validate(library.add_archive(record))


@router.delete("/archive/{archive_id}", status_code=204)
async def delete_archive(
    archive_id: str,
    storage: LocalStorage = Depends(get_storage),
    library: Library = Depends(get_library),
) -> Response:
    """从档案删除：索引记录和本地 results 里的成图一起删掉。"""
    record = library.remove_archive(archive_id)
    if record is None:
        raise HTTPException(status_code=404, detail="档案里没有这条记录")

    storage.delete_url(record.result_url)
    return Response(status_code=204)
