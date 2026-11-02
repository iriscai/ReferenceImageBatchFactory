from __future__ import annotations

import argparse
import io
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image, ImageEnhance, ImageFilter, ImageOps


@dataclass(frozen=True)
class Variant:
    name: str
    scale: float
    quality_rounds: tuple[int, ...]
    final_quality: int
    line_restore: float
    contrast: float
    sharpness: float
    unsharp_radius: float
    unsharp_percent: int
    background_noise: float


# Small-output, but sharpened for line art. This keeps the detector-effective
# reduced dimensions from v7_10 while avoiding the globally blurred look.
VARIANTS = [
    Variant("v10_01_small50_q28_sharp", 0.50, (38, 32), 28, 0.55, 1.02, 1.35, 0.9, 90, 0.35),
    Variant("v10_01_text_overlay", 0.50, (38, 32), 28, 0.55, 1.02, 1.35, 0.9, 90, 0.35),
    Variant("v10_02_small50_q24_sharp", 0.50, (34, 28), 24, 0.60, 1.03, 1.45, 0.9, 110, 0.35),
    Variant("v10_03_small50_q20_sharp", 0.50, (30, 24), 20, 0.65, 1.04, 1.55, 0.8, 125, 0.30),
    Variant("v10_04_small46_q24_sharp", 0.46, (34, 28), 24, 0.62, 1.03, 1.45, 0.8, 115, 0.32),
    Variant("v10_05_small46_q20_sharp", 0.46, (30, 24), 20, 0.68, 1.04, 1.55, 0.75, 135, 0.28),
    Variant("v10_06_small42_q22_sharp", 0.42, (32, 26), 22, 0.66, 1.04, 1.55, 0.75, 130, 0.28),
    Variant("v10_07_small40_q20_sharp", 0.40, (30, 24), 20, 0.70, 1.05, 1.65, 0.7, 145, 0.25),
    Variant("v10_08_small36_q20_sharp", 0.36, (30, 24), 20, 0.72, 1.05, 1.70, 0.65, 155, 0.22),
]


def jpeg_roundtrip(img: Image.Image, quality: int) -> Image.Image:
    buffer = io.BytesIO()
    img.convert("RGB").save(buffer, format="JPEG", quality=quality, subsampling=2, optimize=True)
    buffer.seek(0)
    return Image.open(buffer).convert("RGB")


def save_jfif(img: Image.Image, path: Path, quality: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    img.convert("RGB").save(path, format="JPEG", quality=quality, subsampling=2, optimize=True)


def make_line_layer(source: Image.Image, size: tuple[int, int]) -> tuple[np.ndarray, np.ndarray]:
    gray = ImageOps.grayscale(source)
    small_gray = gray.resize(size, Image.Resampling.LANCZOS)
    arr = np.asarray(small_gray, dtype=np.float32)
    line_mask = np.clip((224.0 - arr) / 130.0, 0.0, 1.0)
    line_mask = np.asarray(
        Image.fromarray(np.uint8(line_mask * 255), "L").filter(ImageFilter.GaussianBlur(0.35)),
        dtype=np.float32,
    ) / 255.0
    line_value = np.minimum(arr, 70.0)
    return line_mask[..., None], line_value[..., None]


def text_only_mask(source: Image.Image, size: tuple[int, int]) -> Image.Image:
    """Detect compact dark components that look like text, not long artwork lines."""
    gray = ImageOps.grayscale(source).resize(size, Image.Resampling.LANCZOS)
    arr = np.asarray(gray, dtype=np.uint8)
    dark = arr < 155
    h, w = dark.shape
    seen = np.zeros_like(dark, dtype=bool)
    keep = np.zeros_like(dark, dtype=np.uint8)

    for y in range(h):
        for x in range(w):
            if not dark[y, x] or seen[y, x]:
                continue
            stack = [(y, x)]
            seen[y, x] = True
            pts: list[tuple[int, int]] = []
            while stack:
                cy, cx = stack.pop()
                pts.append((cy, cx))
                for dy in (-1, 0, 1):
                    for dx in (-1, 0, 1):
                        if dy == 0 and dx == 0:
                            continue
                        ny, nx = cy + dy, cx + dx
                        if 0 <= ny < h and 0 <= nx < w and dark[ny, nx] and not seen[ny, nx]:
                            seen[ny, nx] = True
                            stack.append((ny, nx))
            area = len(pts)
            if area < 3 or area > 420:
                continue
            ys = [p[0] for p in pts]
            xs = [p[1] for p in pts]
            bw = max(xs) - min(xs) + 1
            bh = max(ys) - min(ys) + 1
            if bw > 80 or bh > 48:
                continue
            ratio = bw / max(1, bh)
            fill = area / max(1, bw * bh)
            # Text components are compact. Long contours, character outlines, and
            # drawing strokes are usually too wide/tall/sparse for these limits.
            if 0.12 <= ratio <= 8.0 and 0.08 <= fill <= 0.78:
                keep[min(ys):max(ys) + 1, min(xs):max(xs) + 1] = np.maximum(
                    keep[min(ys):max(ys) + 1, min(xs):max(xs) + 1],
                    dark[min(ys):max(ys) + 1, min(xs):max(xs) + 1].astype(np.uint8) * 255,
                )
    mask = Image.fromarray(keep, "L").filter(ImageFilter.MaxFilter(3)).filter(ImageFilter.GaussianBlur(0.18))
    return mask


def overlay_text_detail(processed: Image.Image, source: Image.Image, strength: float = 0.86) -> Image.Image:
    base = processed.convert("RGB")
    size = base.size
    src_small = ImageOps.exif_transpose(source).convert("RGB").resize(size, Image.Resampling.LANCZOS)
    mask = np.asarray(text_only_mask(source, size), dtype=np.float32)[..., None] / 255.0
    if float(mask.max()) <= 0.0:
        return base
    sharp_text = src_small.filter(ImageFilter.UnsharpMask(radius=0.45, percent=190, threshold=1))
    base_arr = np.asarray(base, dtype=np.float32)
    text_arr = np.asarray(sharp_text, dtype=np.float32)
    alpha = np.clip(mask * strength, 0.0, 0.9)
    out = base_arr * (1.0 - alpha) + text_arr * alpha
    return Image.fromarray(np.uint8(np.clip(out, 0, 255)), "RGB")


def process_variant(source: Image.Image, variant: Variant, rng: np.random.Generator) -> Image.Image:
    original = ImageOps.exif_transpose(source).convert("RGB")
    w, h = original.size
    size = (max(1, int(w * variant.scale)), max(1, int(h * variant.scale)))

    small = original.resize(size, Image.Resampling.LANCZOS)
    small = ImageEnhance.Contrast(small).enhance(variant.contrast)
    small = ImageEnhance.Sharpness(small).enhance(variant.sharpness)
    small = small.filter(ImageFilter.UnsharpMask(radius=variant.unsharp_radius, percent=variant.unsharp_percent, threshold=2))

    arr = np.asarray(small, dtype=np.float32)
    line_mask, line_value = make_line_layer(original, size)
    restored_line = np.repeat(line_value, 3, axis=2)
    arr = arr * (1.0 - line_mask * variant.line_restore) + restored_line * (line_mask * variant.line_restore)

    if variant.background_noise > 0:
        gray = np.asarray(ImageOps.grayscale(Image.fromarray(np.uint8(np.clip(arr, 0, 255)), "RGB")), dtype=np.float32)
        background = np.clip((gray - 165.0) / 90.0, 0.0, 1.0)[..., None]
        arr += rng.normal(0.0, variant.background_noise, arr.shape).astype(np.float32) * background

    out = Image.fromarray(np.uint8(np.clip(arr, 0, 255)), "RGB")
    for quality in variant.quality_rounds:
        out = jpeg_roundtrip(out, quality)
    if variant.name == "v10_01_text_overlay":
        out = overlay_text_detail(out, original, strength=0.86)
    return out


def metric_line(path: Path) -> str:
    img = Image.open(path).convert("L")
    arr = np.asarray(img, dtype=np.float32)
    gy, gx = np.gradient(arr)
    edge = np.hypot(gx, gy)
    h, w = arr.shape
    boundary = [np.abs(arr[:, x] - arr[:, x - 1]).mean() for x in range(8, w, 8)]
    non_boundary = [np.abs(arr[:, x] - arr[:, x - 1]).mean() for x in range(4, w, 8)]
    block_ratio = float(np.mean(boundary) / max(np.mean(non_boundary), 1e-6))
    return (
        f"{path.name}\tbytes={path.stat().st_size}\tsize={w}x{h}\t"
        f"edge_p95={np.percentile(edge, 95):.2f}\tblock_ratio={block_ratio:.3f}"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Small but sharpened line-art variants.")
    parser.add_argument("source", type=Path)
    parser.add_argument("-o", "--output-dir", type=Path, default=None)
    parser.add_argument("--seed", type=int, default=2026070610)
    args = parser.parse_args()

    output_dir = args.output_dir or args.source.parent
    source = Image.open(args.source)
    rng = np.random.default_rng(args.seed)

    for variant in VARIANTS:
        img = process_variant(source, variant, rng)
        out_path = output_dir / f"{args.source.stem}_{variant.name}.jfif"
        save_jfif(img, out_path, variant.final_quality)
        print(metric_line(out_path))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
