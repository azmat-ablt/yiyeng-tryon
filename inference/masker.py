"""基于 SCHP 人体解析的试衣遮罩。

CatVTON 官方 AutoMasker 依赖 Detectron2 + DensePose，在 Windows 上很难编译。
这里保留官方的遮罩算法，但把 DensePose 部分置空，只使用纯 PyTorch 的 SCHP，
因此手部、脚部的强保护会弱一些，上衣试穿场景下影响有限。
"""

import cv2
import numpy as np
from PIL import Image

ATR_MAPPING = {
    "Background": 0, "Hat": 1, "Hair": 2, "Sunglasses": 3,
    "Upper-clothes": 4, "Skirt": 5, "Pants": 6, "Dress": 7,
    "Belt": 8, "Left-shoe": 9, "Right-shoe": 10, "Face": 11,
    "Left-leg": 12, "Right-leg": 13, "Left-arm": 14, "Right-arm": 15,
    "Bag": 16, "Scarf": 17,
}

LIP_MAPPING = {
    "Background": 0, "Hat": 1, "Hair": 2, "Glove": 3,
    "Sunglasses": 4, "Upper-clothes": 5, "Dress": 6, "Coat": 7,
    "Socks": 8, "Pants": 9, "Jumpsuits": 10, "Scarf": 11,
    "Skirt": 12, "Face": 13, "Left-arm": 14, "Right-arm": 15,
    "Left-leg": 16, "Right-leg": 17, "Left-shoe": 18, "Right-shoe": 19,
}

PROTECT_BODY_PARTS = {
    "upper": ["Left-leg", "Right-leg"],
    "lower": ["Right-arm", "Left-arm", "Face"],
    "overall": [],
    "inner": ["Left-leg", "Right-leg"],
    "outer": ["Left-leg", "Right-leg"],
}

PROTECT_CLOTH_PARTS = {
    "upper": {"ATR": ["Skirt", "Pants"], "LIP": ["Skirt", "Pants"]},
    "lower": {"ATR": ["Upper-clothes"], "LIP": ["Upper-clothes", "Coat"]},
    "overall": {"ATR": [], "LIP": []},
    "inner": {"ATR": ["Dress", "Coat", "Skirt", "Pants"], "LIP": ["Dress", "Coat", "Skirt", "Pants", "Jumpsuits"]},
    "outer": {"ATR": ["Dress", "Pants", "Skirt"], "LIP": ["Upper-clothes", "Dress", "Pants", "Skirt", "Jumpsuits"]},
}

MASK_CLOTH_PARTS = {
    "upper": ["Upper-clothes", "Coat", "Dress", "Jumpsuits"],
    "lower": ["Pants", "Skirt", "Dress", "Jumpsuits"],
    "overall": ["Upper-clothes", "Dress", "Pants", "Skirt", "Coat", "Jumpsuits"],
    "inner": ["Upper-clothes"],
    "outer": ["Coat"],
}


def _part_mask(parts, parse, mapping):
    if isinstance(parts, str):
        parts = [parts]
    mask = np.zeros_like(parse, dtype=bool)
    for part in parts:
        label = mapping.get(part)
        if label is None:
            continue
        if isinstance(label, list):
            for item in label:
                mask |= parse == item
        else:
            mask |= parse == label
    return mask


def _skin_mask(rgb: np.ndarray) -> np.ndarray:
    """RGB 图像上的粗略肤色检测（HSV + YCrCb 双阈值取交集）。"""
    hsv = cv2.cvtColor(rgb, cv2.COLOR_RGB2HSV)
    ycrcb = cv2.cvtColor(rgb, cv2.COLOR_RGB2YCrCb)
    skin_hsv = (
        (hsv[..., 0] <= 25)
        & (hsv[..., 1] >= 30)
        & (hsv[..., 1] <= 200)
        & (hsv[..., 2] >= 60)
    )
    skin_ycrcb = (
        (ycrcb[..., 0] >= 70)
        & (ycrcb[..., 1] >= 130)
        & (ycrcb[..., 1] <= 180)
        & (ycrcb[..., 2] >= 80)
        & (ycrcb[..., 2] <= 140)
    )
    return skin_hsv & skin_ycrcb


def hand_mask(
    rgb: np.ndarray, lip_parse: np.ndarray, band: float = 0.35, min_area_ratio: float = 0.0012
) -> np.ndarray:
    """粗略估计手部区域。

    SCHP 没有 hand 类别，官方 AutoMasker 依赖 DensePose，Windows 下不可用。
    这里用「LIP 手臂区域下部带内的肤色像素」近似手与袖口位置，
    只用于把这块从重绘区里排除，避免扩散模型把手指画糊。
    """
    height, width = lip_parse.shape
    skin = _skin_mask(rgb)
    hands = np.zeros((height, width), dtype=bool)
    rows = np.arange(height)[:, None]

    for name in ("Left-arm", "Right-arm"):
        arm = _part_mask(name, lip_parse, LIP_MAPPING)
        ys, xs = np.nonzero(arm)
        if xs.size == 0:
            continue
        arm_h = float(ys.max() - ys.min())
        if arm_h < 0.06 * height:
            continue
        # 手臂下垂时，手在手臂包围盒的下段；取这一段里的肤色像素
        lower_band = arm & (rows > ys.min() + (1 - band) * arm_h)
        candidate = skin & lower_band
        if candidate.sum() < min_area_ratio * width * height:
            continue
        hands |= candidate

    if not hands.any():
        return hands

    kernel = np.ones((5, 5), np.uint8)
    hands = cv2.dilate(hands.astype(np.uint8), kernel, iterations=1).astype(bool)
    return hands


def _hull(mask_area: np.ndarray) -> np.ndarray:
    contours, _ = cv2.findContours(mask_area, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    hull = np.zeros_like(mask_area)
    for contour in contours:
        hull = cv2.fillPoly(np.zeros_like(mask_area), [cv2.convexHull(contour)], 255) | hull
    return hull


def build_mask(
    lip_parse: np.ndarray, atr_parse: np.ndarray, part: str = "upper", extra_protect: np.ndarray | None = None
) -> Image.Image:
    """按 CatVTON 的规则生成衣物区域遮罩（灰度图，255 表示需要重绘）。"""
    height, width = lip_parse.shape

    dilate_kernel = max(width, height) // 250
    dilate_kernel = dilate_kernel if dilate_kernel % 2 == 1 else dilate_kernel + 1
    dilate_kernel = np.ones((dilate_kernel, dilate_kernel), np.uint8)

    blur_kernel = max(width, height) // 25
    blur_kernel = blur_kernel if blur_kernel % 2 == 1 else blur_kernel + 1

    face = _part_mask("Face", lip_parse, LIP_MAPPING)

    body = _part_mask(PROTECT_BODY_PARTS[part], lip_parse, LIP_MAPPING) | _part_mask(
        PROTECT_BODY_PARTS[part], atr_parse, ATR_MAPPING
    )
    hair = _part_mask("Hair", lip_parse, LIP_MAPPING) | _part_mask("Hair", atr_parse, ATR_MAPPING)
    other_clothes = _part_mask(PROTECT_CLOTH_PARTS[part]["LIP"], lip_parse, LIP_MAPPING) | _part_mask(
        PROTECT_CLOTH_PARTS[part]["ATR"], atr_parse, ATR_MAPPING
    )
    accessories = _part_mask(
        ["Hat", "Glove", "Sunglasses", "Bag", "Left-shoe", "Right-shoe", "Scarf", "Socks"],
        lip_parse,
        LIP_MAPPING,
    ) | _part_mask(["Hat", "Sunglasses", "Bag", "Scarf", "Left-shoe", "Right-shoe"], atr_parse, ATR_MAPPING)

    strong_protect = face
    if extra_protect is not None:
        strong_protect = strong_protect | extra_protect
    weak_protect = body | hair | other_clothes | accessories | strong_protect

    mask_clothes = _part_mask(MASK_CLOTH_PARTS[part], lip_parse, LIP_MAPPING) | _part_mask(
        MASK_CLOTH_PARTS[part], atr_parse, ATR_MAPPING
    )
    background = _part_mask("Background", lip_parse, LIP_MAPPING) & _part_mask(
        "Background", atr_parse, ATR_MAPPING
    )

    mask_area = (~weak_protect) & (~background)
    mask_area = _hull((mask_area * 255).astype(np.uint8)) // 255
    mask_area = mask_area.astype(bool) & (~weak_protect)

    blurred = cv2.GaussianBlur((mask_area * 255).astype(np.uint8), (blur_kernel, blur_kernel), 0)
    blurred = (blurred >= 25).astype(np.uint8)

    mask_area = (blurred.astype(bool) | mask_clothes) & (~strong_protect)
    mask_area = cv2.dilate(mask_area.astype(np.uint8), dilate_kernel, iterations=1).astype(bool)
    # 膨胀会把边界重新推进脸部，这里再剔除一次，保证脸部完全不参与重绘
    mask_area = mask_area & (~strong_protect)

    return Image.fromarray(mask_area.astype(np.uint8) * 255)


class SchpMasker:
    def __init__(self, schp_dir: str, device: str = "cuda") -> None:
        from model.SCHP import SCHP

        self._lip = SCHP(f"{schp_dir}/exp-schp-201908261155-lip.pth", device=device)
        self._atr = SCHP(f"{schp_dir}/exp-schp-201908301523-atr.pth", device=device)

    def __call__(self, image: Image.Image, mask_type: str = "upper") -> Image.Image:
        rgb = np.asarray(image)
        lip_parse = np.array(self._lip(image))
        atr_parse = np.array(self._atr(image))
        hands = hand_mask(rgb, lip_parse)
        return build_mask(lip_parse, atr_parse, part=mask_type, extra_protect=hands)

    def extract_worn_garment(self, image: Image.Image, part: str = "upper") -> Image.Image | None:
        """衣物图若是「穿在人身上」的效果图，把衣物单独抠出来做成平铺图。

        用户上传的衣物图大多是模特上身图；直接送进 CatVTON 会把人的体型、肤色
        甚至脸部一并当成衣服参考。这里只保留衣物像素，其余填白。
        返回 None 表示这张图本身就是平铺衣物图，按原样使用。
        """
        rgb = np.asarray(image)
        lip_parse = np.array(self._lip(image))
        atr_parse = np.array(self._atr(image))
        if lip_parse.ndim == 3:
            lip_parse = lip_parse[:, :, 0]
        if atr_parse.ndim == 3:
            atr_parse = atr_parse[:, :, 0]

        garment = _part_mask(MASK_CLOTH_PARTS[part], lip_parse, LIP_MAPPING) | _part_mask(
            MASK_CLOTH_PARTS[part], atr_parse, ATR_MAPPING
        )
        body = _part_mask(
            ["Face", "Hair", "Left-arm", "Right-arm", "Left-leg", "Right-leg"], lip_parse, LIP_MAPPING
        )
        height, width = garment.shape
        if garment.mean() < 0.04 or body.mean() < 0.02:
            return None

        area = cv2.GaussianBlur(cv2.dilate(garment.astype(np.uint8), np.ones((5, 5), np.uint8), 1) * 255, (5, 5), 0)
        alpha = (area / 255.0)[:, :, None]
        canvas = np.full_like(rgb, 255, dtype=np.float32)
        canvas = canvas * (1 - alpha) + rgb.astype(np.float32) * alpha

        ys, xs = np.nonzero(garment)
        pad_x = int((xs.max() - xs.min()) * 0.06)
        pad_y = int((ys.max() - ys.min()) * 0.06)
        box = (
            max(int(xs.min()) - pad_x, 0),
            max(int(ys.min()) - pad_y, 0),
            min(int(xs.max()) + pad_x, width),
            min(int(ys.max()) + pad_y, height),
        )
        return Image.fromarray(canvas.clip(0, 255).astype(np.uint8)).crop(box)

    def head_alpha(self, image: Image.Image, dilate_ratio: float = 0.004, feather: int = 7) -> Image.Image:
        """返回头部（脸 + 头发）的软遮罩（L 模式，255 表示保留原图），用于生成后贴回原图。"""
        lip_parse = np.array(self._lip(image))
        if lip_parse.ndim == 3:
            lip_parse = lip_parse[:, :, 0]

        head = _part_mask(["Face", "Hair"], lip_parse, LIP_MAPPING)
        if not head.any():
            return Image.new("L", image.size, 0)

        kernel_size = max(3, int(min(image.size) * dilate_ratio))
        kernel_size = kernel_size if kernel_size % 2 == 1 else kernel_size + 1
        kernel = np.ones((kernel_size, kernel_size), np.uint8)
        head_area = cv2.dilate(head.astype(np.uint8), kernel, iterations=1) * 255
        head_area = cv2.GaussianBlur(head_area, (feather, feather), 0)
        # 头部遮罩向外扩散后会盖住衣领，贴回时会把旧衣服带到新图里，这里按服装区域扣掉
        clothes = _part_mask(["Upper-clothes", "Coat", "Dress", "Jumpsuits"], lip_parse, LIP_MAPPING)
        head_area[clothes] = 0
        return Image.fromarray(head_area)
