import io
import logging
import os
import tempfile
import threading
from contextlib import asynccontextmanager
from pathlib import Path

os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")
os.environ.setdefault("HF_HOME", str(Path(__file__).resolve().parent / ".hf-cache"))

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import Response

from catvton_runner import CatVTonRunner, InputValidationError

logger = logging.getLogger("catvton")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

runner = CatVTonRunner(
    device=os.getenv("CATVTON_DEVICE", "cuda"),
    width=int(os.getenv("CATVTON_WIDTH", "768")),
    height=int(os.getenv("CATVTON_HEIGHT", "1024")),
    steps=int(os.getenv("CATVTON_STEPS", "20")),
)
generate_lock = threading.Lock()


def _preload() -> None:
    try:
        logger.info("正在加载 CatVTON 模型…")
        runner.load()
        logger.info("CatVTON 模型加载完成")
    except Exception:
        logger.exception("CatVTON 模型加载失败")


@asynccontextmanager
async def lifespan(_: FastAPI):
    threading.Thread(target=_preload, daemon=True).start()
    yield


app = FastAPI(title="虚拟试衣推理服务", lifespan=lifespan)


@app.get("/health")
def health() -> dict[str, object]:
    return {
        "status": "ok" if runner.ready else "loading",
        "model": "catvton",
        "ready": runner.ready,
        "device": runner.device,
    }


def _run(person_path: str, garment_path: str, cloth_type: str) -> bytes:
    runner.load()
    with generate_lock:
        image = runner.generate(person_path, garment_path, cloth_type)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


@app.post("/generate")
async def generate(
    person: UploadFile = File(...),
    garment: UploadFile = File(...),
    cloth_type: str = Form("upper"),
) -> Response:
    person_data = await person.read()
    garment_data = await garment.read()
    if not person_data or not garment_data:
        raise HTTPException(status_code=400, detail="图片内容为空")

    with tempfile.TemporaryDirectory() as tmp_dir:
        person_path = os.path.join(tmp_dir, f"person{Path(person.filename or '').suffix or '.png'}")
        garment_path = os.path.join(tmp_dir, f"garment{Path(garment.filename or '').suffix or '.png'}")
        with open(person_path, "wb") as file:
            file.write(person_data)
        with open(garment_path, "wb") as file:
            file.write(garment_data)

        try:
            content = await run_in_threadpool(_run, person_path, garment_path, cloth_type)
        except InputValidationError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except Exception as exc:
            logger.exception("生成失败")
            raise HTTPException(status_code=500, detail=f"生成失败: {exc}") from exc

    return Response(content=content, media_type="image/png")
