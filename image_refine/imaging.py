# -*- coding: utf-8 -*-
"""图像精修处理管线：全部基于 Pillow + numpy 实现。

流程（单张图）：
  1. EXIF 矫正、模式统一为 RGBA；
  2. 按画布比例生成画布，背景 = 原图 cover 放大 + 高斯虚化（或纯色）；
  3. 原图按“包含 + 构图放大”生成前景卡片，按裁切基准定位；
  4. 光影色彩 → 圆角 → 边框 → 投影 → 叠加信息图层 → 颗粒/锐化；
  5. 按原始格式与导出质量编码输出。
"""
from __future__ import annotations

import io
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageEnhance, ImageFile, ImageFilter, ImageOps

# 批量素材来自用户压缩包，尽量宽容
ImageFile.LOAD_TRUNCATED_IMAGES = True
Image.MAX_IMAGE_PIXELS = 300_000_000

# 批量处理时画布长边上限（px），超出会等比缩小，避免内存/耗时失控
MAX_CANVAS_SIDE = 2800
# 预览时长边上限（px），保证预览响应速度；像素参数会按比例同步缩放
PREVIEW_MAX_SIDE = 1400

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}
# 压缩目录内的「叠加图」命名约定（优先级高于全局信息图层）
OVERLAY_STEMS = ("overlay", "叠加图", "叠加", "信息图层")

_RATIO_TABLE = {
    "1:1": 1.0,
    "4:5": 4 / 5,
    "3:4": 3 / 4,
    "2:3": 2 / 3,
    "9:16": 9 / 16,
    "16:9": 16 / 9,
    "3:2": 3 / 2,
}
_ANCHOR_F = {"center": 0.5, "top": 0.0, "bottom": 1.0, "left": 0.0, "right": 1.0}


# ---------------------------------------------------------------- 基础工具

def load_image(data: bytes) -> Image.Image:
    """任意格式字节流 → RGBA 图像（EXIF 方向已矫正）。"""
    img = Image.open(io.BytesIO(data))
    try:
        img = ImageOps.exif_transpose(img)
    except Exception:
        pass
    if img.mode != "RGBA":
        img = img.convert("RGBA")
    return img


def _ratio_value(name: str) -> float | None:
    if name == "original":
        return None
    return _RATIO_TABLE.get(name)


def _canvas_size(iw: int, ih: int, ratio: float | None) -> tuple[int, int]:
    """画布长边 = 原图长边，短边由比例推出，保证清晰度不缩水。"""
    if ratio is None:
        return iw, ih
    long_side = max(iw, ih)
    if ratio >= 1.0:
        return long_side, max(1, round(long_side / ratio))
    return max(1, round(long_side * ratio)), long_side


def _round_mask(size: tuple[int, int], radius: int) -> Image.Image:
    m = Image.new("L", size, 0)
    ImageDraw.Draw(m).rounded_rectangle(
        [0, 0, size[0] - 1, size[1] - 1], radius=radius, fill=255
    )
    return m


def _composite(canvas: Image.Image, src: Image.Image, x: int, y: int) -> None:
    """alpha_composite 的越界安全版：允许负坐标 / 部分溢出。"""
    cw, ch = canvas.size
    sw, sh = src.size
    x0, y0 = max(0, x), max(0, y)
    x1, y1 = min(cw, x + sw), min(ch, y + sh)
    if x1 <= x0 or y1 <= y0:
        return
    sub = src.crop((x0 - x, y0 - y, x1 - x, y1 - y))
    canvas.alpha_composite(sub, (x0, y0))


def _hex_rgba(color: str) -> tuple[int, int, int, int]:
    v = color.lstrip("#")
    return int(v[0:2], 16), int(v[2:4], 16), int(v[4:6], 16), 255


# ---------------------------------------------------------------- 调整步骤

def _apply_color(card: Image.Image, p: dict) -> Image.Image:
    if p["brightness"]:
        card = ImageEnhance.Brightness(card).enhance(1 + p["brightness"] / 100)
    if p["contrast"]:
        card = ImageEnhance.Contrast(card).enhance(1 + p["contrast"] / 100)
    if p["saturation"]:
        card = ImageEnhance.Color(card).enhance(1 + p["saturation"] / 100)
    if p["warmth"]:
        w = p["warmth"] / 100
        arr = np.asarray(card).astype(np.float32)
        arr[..., 0] = np.clip(arr[..., 0] * (1 + 0.25 * w), 0, 255)
        arr[..., 2] = np.clip(arr[..., 2] * (1 - 0.25 * w), 0, 255)
        card = Image.fromarray(arr.astype(np.uint8))
    return card


def _apply_round(card: Image.Image, radius: int) -> Image.Image:
    """圆角：保留卡片自身透明度，仅把角部 alpha 置零。"""
    if radius <= 0:
        return card
    mask = _round_mask(card.size, radius)
    arr = np.asarray(card).copy()
    arr[..., 3] = (arr[..., 3].astype(np.uint16) * np.asarray(mask, dtype=np.uint16) // 255).astype(np.uint8)
    return Image.fromarray(arr)


def _apply_border(card: Image.Image, width: int, color: str, radius: int) -> Image.Image:
    if width <= 0:
        return card
    d = ImageDraw.Draw(card)
    d.rounded_rectangle(
        [0, 0, card.width - 1, card.height - 1],
        radius=radius,
        outline=_hex_rgba(color),
        width=width,
    )
    return card


def _apply_shadow(canvas: Image.Image, card_size: tuple[int, int], radius: int,
                  strength: int, x: int, y: int) -> None:
    s = strength / 100.0
    off = max(2, round(min(card_size) * 0.015))
    pad = off * 5
    mask = _round_mask(card_size, radius)
    alpha = mask.point(lambda v: round(v * 0.55 * s))
    black = Image.new("RGBA", card_size, (20, 20, 35, 255))
    black.putalpha(alpha)
    sh = Image.new("RGBA", (card_size[0] + pad * 2, card_size[1] + pad * 2), (0, 0, 0, 0))
    sh.alpha_composite(black, (pad, pad + off))
    sh = sh.filter(ImageFilter.GaussianBlur(max(1.0, off * 1.4)))
    _composite(canvas, sh, x - pad, y - pad)


def _apply_grain(img: Image.Image, amount: float) -> Image.Image:
    arr = np.asarray(img).astype(np.int16)
    noise = np.random.default_rng().normal(0.0, amount, arr.shape[:2])[..., None]
    arr[..., :3] = np.clip(arr[..., :3] + noise, 0, 255)
    return Image.fromarray(arr.astype(np.uint8))


# ---------------------------------------------------------------- 主流程

def process(img: Image.Image, p: dict, cap_side: int = MAX_CANVAS_SIDE,
            overlay: Image.Image | None = None) -> Image.Image:
    """对单张图执行完整精修管线，返回画布尺寸的 RGBA 结果。"""
    iw, ih = img.size
    # 超大图等比缩小，像素类参数同步缩放（k），保证效果与全尺寸一致
    scale = min(1.0, cap_side / max(iw, ih))
    if scale < 1.0:
        img = img.resize((max(1, round(iw * scale)), max(1, round(ih * scale))), Image.LANCZOS)
        iw, ih = img.size
    k = scale

    ratio = _ratio_value(p["canvas_ratio"])
    cw, ch = _canvas_size(iw, ih, ratio)
    needs_bg = (cw, ch) != (iw, ih)

    # ---- 背景 ----
    if needs_bg and p["bg_blur_enabled"]:
        cover = max(cw / iw, ch / ih) * 1.06  # 多放大一点，避免虚化后边缘发暗
        bw, bh = round(iw * cover) + 1, round(ih * cover) + 1
        bg = img.resize((bw, bh), Image.LANCZOS)
        left, top = (bw - cw) // 2, (bh - ch) // 2
        bg = bg.crop((left, top, left + cw, top + ch))
        bg = bg.filter(ImageFilter.GaussianBlur(max(0.5, p["bg_blur_strength"] * k)))
        canvas = ImageEnhance.Brightness(bg).enhance(1.04).convert("RGBA")
    else:
        canvas = Image.new("RGBA", (cw, ch), (255, 255, 255, 255))

    # ---- 前景卡片：包含适配 × 悬浮系数 × (1+放大)，越界即裁切 ----
    # 指定画布比例时卡片四周留 ~2.5% 边距悬浮在背景上（可用构图放大推进至满铺/裁切）；
    # 原图比例则直接铺满画布
    contain = min(cw / iw, ch / ih)
    inset = 0.95 if ratio is not None else 1.0
    sc = contain * inset * (1 + p["zoom"] / 100.0)
    w, h = max(1, round(iw * sc)), max(1, round(ih * sc))
    card = img.resize((w, h), Image.LANCZOS)

    # ---- 光影色彩 ----
    if p["color_enabled"]:
        card = _apply_color(card, p)

    # ---- 圆角 / 边框 ----
    radius = min(min(w, h) // 2, round(p["radius"] * k)) if p["radius_enabled"] else 0
    card = _apply_round(card, radius)
    if p["border_enabled"]:
        card = _apply_border(card, round(p["border_width"] * k), p["border_color"], radius)

    # ---- 定位（裁切基准）----
    fx = _ANCHOR_F.get(p["crop_anchor"], 0.5) if p["crop_anchor"] in ("left", "right", "center") else 0.5
    fy = _ANCHOR_F.get(p["crop_anchor"], 0.5) if p["crop_anchor"] in ("top", "bottom", "center") else 0.5
    x, y = round((cw - w) * fx), round((ch - h) * fy)

    # ---- 投影 + 合成 ----
    if p["shadow_enabled"] and p["shadow_strength"] > 0 and needs_bg:
        _apply_shadow(canvas, (w, h), radius, p["shadow_strength"], x, y)
    _composite(canvas, card, x, y)

    # ---- 信息图层（拉伸铺满画布）----
    if overlay is not None:
        ov = overlay.resize((cw, ch), Image.LANCZOS).convert("RGBA")
        canvas.alpha_composite(ov)

    # ---- 质感：颗粒 + 锐化（作用于整幅输出）----
    if p["texture_enabled"]:
        if p["grain"] > 0:
            canvas = _apply_grain(canvas, p["grain"] * 0.8)
        if p["sharpness"] > 0:
            canvas = canvas.filter(
                ImageFilter.UnsharpMask(radius=1.6, percent=int(p["sharpness"] * 10), threshold=3)
            )
    return canvas


def export_bytes(img: Image.Image, filename: str, quality: int) -> bytes:
    """按原文件扩展名编码；JPG/BMP 透明区域落白底；质量参数对 JPG/WebP 生效。"""
    ext = Path(filename).suffix.lower()
    buf = io.BytesIO()
    if ext in (".jpg", ".jpeg"):
        flat = Image.new("RGB", img.size, (255, 255, 255))
        flat.paste(img, (0, 0), img)
        flat.save(buf, "JPEG", quality=int(quality), subsampling=0 if quality >= 90 else 2)
    elif ext == ".webp":
        img.save(buf, "WEBP", quality=int(quality))
    elif ext == ".bmp":
        flat = Image.new("RGB", img.size, (255, 255, 255))
        flat.paste(img, (0, 0), img)
        flat.save(buf, "BMP")
    else:  # png 及未知扩展名一律落 PNG（无损）
        img.save(buf, "PNG", optimize=True)
    return buf.getvalue()
