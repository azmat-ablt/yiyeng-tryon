"""CatVTON 推理封装。"""

import os
import sys
import threading
from pathlib import Path

import cv2
import numpy as np
import torch
from PIL import Image

VENDOR_DIR = Path(__file__).resolve().parent / "vendor" / "CatVTON-main"
if str(VENDOR_DIR) not in sys.path:
    sys.path.insert(0, str(VENDOR_DIR))
if str(Path(__file__).resolve().parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parent))

from model.pipeline import CatVTONPipeline  # noqa: E402
from utils import resize_and_crop, resize_and_padding  # noqa: E402

from masker import LIP_MAPPING, SchpMasker  # noqa: E402

MODEL_DIR = Path(__file__).resolve().parent / "models"


class InputValidationError(ValueError):
    """上传的图片不满足试衣要求，消息会直接展示给用户。"""


class CatVTonRunner:
    def __init__(
        self,
        base_ckpt: str | None = None,
        attn_ckpt: str | None = None,
        attn_version: str = "mix",
        device: str = "cuda",
        width: int = 768,
        height: int = 1024,
        steps: int = 20,
        guidance_scale: float = 2.5,
        seed: int | None = 42,
    ) -> None:
        self.base_ckpt = base_ckpt or self._default_base_ckpt()
        self.attn_ckpt = attn_ckpt or self._default_attn_ckpt()
        self.attn_version = attn_version
        self.device = device
        self.width = width
        self.height = height
        self.steps = steps
        self.guidance_scale = guidance_scale
        self.seed = seed

        self._lock = threading.Lock()
        self._pipeline: CatVTONPipeline | None = None
        self._masker: SchpMasker | None = None

    @staticmethod
    def _default_base_ckpt() -> str:
        local = MODEL_DIR / "base-inpainting"
        return str(local) if (local / "unet").exists() else "runwayml/stable-diffusion-inpainting"

    @staticmethod
    def _default_attn_ckpt() -> str:
        local = MODEL_DIR / "catvton"
        return str(local) if (local / "mix-48k-1024").exists() else "zhengchong/CatVTON"

    @property
    def ready(self) -> bool:
        return self._pipeline is not None

    def _resolve_schp_dir(self, attn_ckpt: str) -> str:
        local = Path(attn_ckpt) / "SCHP"
        if local.exists():
            return str(local)

        from huggingface_hub import snapshot_download

        return os.path.join(snapshot_download(repo_id=attn_ckpt, allow_patterns=["SCHP/*"]), "SCHP")

    def load(self) -> None:
        """加载模型，重复调用只会加载一次。"""
        with self._lock:
            if self._pipeline is not None:
                return
            if not torch.cuda.is_available():
                raise RuntimeError("未检测到可用的 CUDA 设备")

            vae_dir = MODEL_DIR / "vae"
            if vae_dir.exists():
                os.environ.setdefault("CATVTON_VAE_PATH", str(vae_dir))

            self._pipeline = CatVTONPipeline(
                base_ckpt=self.base_ckpt,
                attn_ckpt=self.attn_ckpt,
                attn_ckpt_version=self.attn_version,
                weight_dtype=torch.bfloat16,
                device=self.device,
                skip_safety_check=True,
                use_tf32=True,
            )
            self._masker = SchpMasker(self._resolve_schp_dir(self.attn_ckpt), device=self.device)

    @torch.no_grad()
    def generate(self, person_path: str, garment_path: str, cloth_type: str = "upper") -> Image.Image:
        if self._pipeline is None or self._masker is None:
            raise RuntimeError("模型尚未加载")

        original = self._open_image(person_path, "人像")
        garment = self._open_image(garment_path, "衣物")
        self._validate_garment(garment)
        frame = resize_and_crop(original, (self.width, self.height))
        frame_parse = self._parse_frame(frame)
        self._validate_person(original, frame, frame_parse)

        # 人物在画面里太小时，脸部只有几十像素，扩散模型很难画准；
        # 先按人物包围盒裁切并放大到模型分辨率，生成后再按原位缩放贴回。
        box_orig, box_frame = self._subject_boxes(original, frame, frame_parse)
        person = resize_and_crop(original.crop(box_orig), (self.width, self.height))
        worn = self._masker.extract_worn_garment(garment, part=cloth_type)
        if worn is not None:
            # 用户上传的是「模特上身图」，先抠成平铺衣物再作为参考图
            garment = worn
        garment = resize_and_padding(garment, (self.width, self.height))
        mask = self._masker(person, mask_type=cloth_type)

        generator = None
        if self.seed is not None:
            generator = torch.Generator(device=self.device).manual_seed(self.seed)

        results = self._pipeline(
            person,
            garment,
            mask,
            num_inference_steps=self.steps,
            guidance_scale=self.guidance_scale,
            height=self.height,
            width=self.width,
            generator=generator,
        )
        generated = results[0]

        # 扩散模型会整体改变画面色调，新衣服容易和原图场景光不融；
        # 用未被重绘的区域（背景、皮肤、下装）估计色偏，再校正到衣物区域。
        generated = self._match_scene_lighting(generated, person, mask)

        # 面部、头发、手、以及遮罩外的区域都按软遮罩贴回原图，
        # 既保证长相不变，也避免手部和皮肤被 VAE 重编码糊掉。
        keep = self._restore_alpha(person, mask)
        result = Image.composite(person, generated, keep)

        if box_frame == (0, 0, self.width, self.height):
            return result

        result = result.resize((box_frame[2] - box_frame[0], box_frame[3] - box_frame[1]), Image.LANCZOS)
        frame.paste(result, box_frame[:2], self._feather_alpha(result.size))
        return frame

    @staticmethod
    def _open_image(path: str, label: str) -> Image.Image:
        try:
            image = Image.open(path)
            image.load()
            return image.convert("RGB")
        except Exception as exc:  # noqa: BLE001
            raise InputValidationError(f"{label}图片无法解析，请上传 JPG/PNG 格式的图片") from exc

    @staticmethod
    def _validate_garment(garment: Image.Image) -> None:
        if min(garment.size) < 128:
            raise InputValidationError("衣物图片分辨率过低，请上传边长至少 128 像素的清晰平铺图")
        small = np.asarray(garment.convert("L").resize((64, 64)), dtype=np.float32)
        if float(small.std()) < 3.0:
            raise InputValidationError("衣物图片几乎是纯色，无法识别衣物，请重新上传")

    def _parse_frame(self, frame: Image.Image) -> np.ndarray:
        parse = np.array(self._masker._lip(frame))
        return parse[:, :, 0] if parse.ndim == 3 else parse

    def _validate_person(self, original: Image.Image, frame: Image.Image, parse: np.ndarray) -> None:
        if min(original.size) < 200:
            raise InputValidationError("人像图片分辨率过低，请上传短边至少 200 像素的照片")

        body = parse != LIP_MAPPING["Background"]
        if float(body.mean()) < 0.03:
            raise InputValidationError("未识别到人物主体，请上传人物占画面比例较大的清晰人像")

        face = parse == LIP_MAPPING["Face"]
        ys, xs = np.nonzero(face)
        if xs.size == 0:
            raise InputValidationError("未检测到人脸，请上传正脸或侧脸清晰的人像照片")
        face_h = float(ys.max() - ys.min())
        face_w = float(xs.max() - xs.min())
        if face_h < 0.02 * self.height or face_w < 0.015 * self.width:
            raise InputValidationError("人像中的人脸过小或不够清晰，请上传更近的人像照片")

    def _subject_boxes(
        self, original: Image.Image, frame: Image.Image, parse: np.ndarray
    ) -> tuple[tuple[int, int, int, int], tuple[int, int, int, int]]:
        """返回人物裁切框（原图坐标、输出画幅坐标），保持目标宽高比并留边。"""
        full_orig = (0, 0, original.width, original.height)
        full_frame = (0, 0, self.width, self.height)

        body = parse != LIP_MAPPING["Background"]
        ys, xs = np.nonzero(body)
        if xs.size < 0.02 * self.width * self.height:
            return full_orig, full_frame

        ratio = self.width / self.height
        center_x = (float(xs.min()) + float(xs.max())) / 2
        center_y = (float(ys.min()) + float(ys.max())) / 2
        box_w = (float(xs.max()) - float(xs.min())) * 1.16
        box_h = (float(ys.max()) - float(ys.min())) * 1.16
        if box_w / box_h < ratio:
            box_w = box_h * ratio
        else:
            box_h = box_w / ratio
        box_w = min(box_w, float(self.width))
        box_h = min(box_h, float(self.height))
        left = min(max(center_x - box_w / 2, 0.0), self.width - box_w)
        top = min(max(center_y - box_h / 2, 0.0), self.height - box_h)

        scale_x = original.width / self.width
        scale_y = original.height / self.height
        box_orig = (
            round(left * scale_x),
            round(top * scale_y),
            round((left + box_w) * scale_x),
            round((top + box_h) * scale_y),
        )
        box_frame = (
            round(left),
            round(top),
            round(left + box_w),
            round(top + box_h),
        )
        return box_orig, box_frame

    @staticmethod
    def _match_scene_lighting(generated: Image.Image, original: Image.Image, mask: Image.Image) -> Image.Image:
        """按未重绘区域统计色偏，把生成结果的衣物区域拉回原图的光照与肤色。"""
        keep_region = np.asarray(mask) < 128
        if keep_region.sum() < 0.05 * keep_region.size:
            return generated

        gen_lab = cv2.cvtColor(np.asarray(generated, dtype=np.uint8), cv2.COLOR_RGB2LAB).astype(np.float32)
        ref_lab = cv2.cvtColor(np.asarray(original, dtype=np.uint8), cv2.COLOR_RGB2LAB).astype(np.float32)

        ys, xs = np.nonzero(keep_region)
        step = max(1, xs.size // 20000)
        ys, xs = ys[::step], xs[::step]
        gen_px = gen_lab[ys, xs]
        ref_px = ref_lab[ys, xs]

        gen_mean, gen_std = gen_px.mean(axis=0), gen_px.std(axis=0)
        ref_mean, ref_std = ref_px.mean(axis=0), ref_px.std(axis=0)
        gain = np.clip(ref_std / np.maximum(gen_std, 1e-3), 0.85, 1.18)
        bias = np.clip(ref_mean - gain * gen_mean, -10.0, 10.0)
        if float(np.abs(bias).max()) < 1.5 and float(np.abs(gain - 1).max()) < 0.02:
            return generated

        corrected_lab = np.clip(gen_lab * gain + bias, 0, 255).astype(np.uint8)
        corrected = cv2.cvtColor(corrected_lab, cv2.COLOR_LAB2RGB).astype(np.float32)

        kernel = max(3, int(round(min(generated.size) / 200)))
        kernel = kernel if kernel % 2 == 1 else kernel + 1
        alpha = cv2.GaussianBlur((~keep_region).astype(np.uint8) * 255, (kernel, kernel), 0)
        alpha = (alpha / 255.0)[:, :, None]

        blended = np.asarray(generated, dtype=np.float32) * (1 - alpha) + corrected * alpha
        return Image.fromarray(np.clip(blended, 0, 255).astype(np.uint8))

    def _restore_alpha(self, person: Image.Image, mask: Image.Image) -> Image.Image:
        """返回需要保留原图区域的软遮罩：遮罩外的所有像素 + 头部。"""
        outside = (np.asarray(mask) < 128).astype(np.uint8) * 255
        kernel = max(3, int(round(min(person.size) / 200)))
        kernel = kernel if kernel % 2 == 1 else kernel + 1
        outside = cv2.GaussianBlur(outside, (kernel, kernel), 0).astype(np.float32) / 255.0
        # 轻微压缩过渡带，避免生成区域边缘露出旧衣服的轮廓
        outside = np.clip(outside, 0, 1) ** 1.4

        head = np.asarray(self._masker.head_alpha(person), dtype=np.float32) / 255.0
        alpha = np.maximum(outside, head)
        return Image.fromarray((alpha * 255).astype(np.uint8))

    @staticmethod
    def _feather_alpha(size: tuple[int, int], feather: int = 12) -> Image.Image:
        width, height = size
        feather = max(1, min(feather, width // 2, height // 2))
        ramp_x = np.clip(np.arange(width) / feather, 0, 1)
        ramp_x = np.minimum(ramp_x, ramp_x[::-1])
        ramp_y = np.clip(np.arange(height) / feather, 0, 1)
        ramp_y = np.minimum(ramp_y, ramp_y[::-1])
        alpha = (ramp_y[:, None] * ramp_x[None, :] * 255).astype(np.uint8)
        return Image.fromarray(alpha)
