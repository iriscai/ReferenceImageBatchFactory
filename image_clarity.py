from __future__ import annotations

import argparse
import importlib
import shutil
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable

import numpy as np
from PIL import Image, ImageEnhance, ImageFilter, ImageOps


IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".jfif", ".webp", ".bmp", ".tif", ".tiff"}
LINE_PRESSURE_METHOD = "v10_01_text"
POSTPROCESS_ORIGINAL = "original"
POSTPROCESS_OPTIMIZED = "optimized"
POSTPROCESS_MODES = (POSTPROCESS_ORIGINAL, POSTPROCESS_OPTIMIZED)
PipelineProgress = Callable[[str, int, int, Path, Path | None, str | None], None]


@dataclass(slots=True)
class ClaritySettings:
    max_dimension: int = 798
    sharpen_percent: int = 50
    contrast: float = 1.015
    clean_background: bool = True
    denoise: bool = True
    jpeg_quality: int = 95


def open_image(path: Path) -> Image.Image:
    with Image.open(path) as opened:
        return ImageOps.exif_transpose(opened).convert("RGB")


def resize_first(image: Image.Image, max_dimension: int) -> tuple[Image.Image, float, float]:
    """Resize proportionally so the longest edge equals max_dimension."""
    if max_dimension <= 0:
        raise ValueError("max_dimension must be greater than 0")
    scale = max_dimension / max(image.width, image.height)
    width = max(1, round(image.width * scale))
    height = max(1, round(image.height * scale))
    x_scale = width / image.width
    y_scale = height / image.height
    if (width, height) == image.size:
        return image.copy(), x_scale, y_scale
    return image.resize((width, height), Image.Resampling.LANCZOS, reducing_gap=3.0), x_scale, y_scale


def _luma_and_chroma(image: Image.Image) -> tuple[np.ndarray, np.ndarray]:
    arr = np.asarray(image).astype(np.float32)
    luma = arr[..., 0] * 0.299 + arr[..., 1] * 0.587 + arr[..., 2] * 0.114
    chroma = arr.max(axis=2) - arr.min(axis=2)
    return luma, chroma


def _sharpen_luma(image: Image.Image, settings: ClaritySettings) -> Image.Image:
    ycbcr = image.convert("YCbCr")
    y, cb, cr = ycbcr.split()
    y = ImageEnhance.Contrast(y).enhance(settings.contrast)
    y = y.filter(
        ImageFilter.UnsharpMask(
            radius=0.65,
            percent=max(0, settings.sharpen_percent),
            threshold=9,
        )
    )
    return Image.merge("YCbCr", (y, cb, cr)).convert("RGB")


def _foreground_preserving_clean(image: Image.Image, settings: ClaritySettings) -> Image.Image:
    """Sharpen dark/colorful foreground while leaving the original background intact."""
    original = image.convert("RGB")
    luma, chroma = _luma_and_chroma(original)
    # Neutral bright pixels are treated as paper/background. A max filter adds
    # a small halo so anti-aliased line edges receive the same cleanup.
    foreground = ((luma < 226.0) | (chroma > 28.0)).astype(np.uint8) * 255
    mask = Image.fromarray(foreground, "L").filter(ImageFilter.MaxFilter(size=5))
    mask = mask.filter(ImageFilter.GaussianBlur(radius=0.7))
    sharpened = _sharpen_luma(original, settings)
    return Image.composite(sharpened, original, mask)


def _line_context_mask(image: Image.Image) -> tuple[np.ndarray, np.ndarray]:
    """Return a conservative dark-line mask and a small anti-aliasing context."""
    luma, chroma = _luma_and_chroma(image)
    # Colored fills are intentionally excluded. They are often pale green,
    # yellow, or blue and should keep their original texture and tone.
    dark_seed = luma < 178.0
    line_mask = Image.fromarray(np.uint8(dark_seed) * 255, "L")
    line_mask = line_mask.filter(ImageFilter.MaxFilter(size=3))
    line_context = line_mask.filter(ImageFilter.MaxFilter(size=5)).filter(ImageFilter.GaussianBlur(radius=0.65))
    return np.asarray(line_mask).astype(np.float32) / 255.0, np.asarray(line_context).astype(np.float32) / 255.0


def _dense_artwork_mask(image: Image.Image) -> np.ndarray:
    """Select locally dense artwork without selecting open background areas."""
    luma, chroma = _luma_and_chroma(image)
    seed = (luma < 220.0) | ((chroma > 18.0) & (luma < 248.0))
    density = Image.fromarray(np.uint8(seed) * 255, "L").filter(ImageFilter.GaussianBlur(radius=11.0))
    density_arr = np.asarray(density).astype(np.float32)
    mask = np.clip((density_arr - 8.0) / 26.0, 0.0, 1.0)
    mask_image = Image.fromarray(np.uint8(mask * 255), "L")
    mask_image = mask_image.filter(ImageFilter.MaxFilter(size=9)).filter(ImageFilter.GaussianBlur(radius=2.0))
    return np.asarray(mask_image).astype(np.float32) / 255.0


def _detect_text_rows(image: Image.Image) -> list[tuple[int, int, int, int]]:
    """Find aligned compact dark components that form text rows."""
    arr = np.asarray(image.convert("RGB"), dtype=np.float32)
    luma = np.uint8(arr[..., 0] * 0.299 + arr[..., 1] * 0.587 + arr[..., 2] * 0.114)
    dark = luma < 155
    height, width = dark.shape
    visited = np.zeros_like(dark, dtype=bool)
    components: list[tuple[int, int, int, int, int, float, float]] = []

    for start_y in range(height):
        for start_x in range(width):
            if not dark[start_y, start_x] or visited[start_y, start_x]:
                continue
            stack = [(start_y, start_x)]
            visited[start_y, start_x] = True
            min_x = max_x = start_x
            min_y = max_y = start_y
            area = 0
            sum_x = sum_y = 0
            while stack:
                current_y, current_x = stack.pop()
                area += 1
                min_x = min(min_x, current_x)
                max_x = max(max_x, current_x)
                min_y = min(min_y, current_y)
                max_y = max(max_y, current_y)
                sum_x += current_x
                sum_y += current_y
                for delta_y in (-1, 0, 1):
                    for delta_x in (-1, 0, 1):
                        if delta_y == 0 and delta_x == 0:
                            continue
                        next_y = current_y + delta_y
                        next_x = current_x + delta_x
                        if (
                            0 <= next_y < height
                            and 0 <= next_x < width
                            and dark[next_y, next_x]
                            and not visited[next_y, next_x]
                        ):
                            visited[next_y, next_x] = True
                            stack.append((next_y, next_x))
            component_width = max_x - min_x + 1
            component_height = max_y - min_y + 1
            fill = area / max(1, component_width * component_height)
            ratio = component_width / max(1, component_height)
            if (
                35 <= area <= 1400
                and 7 <= component_width <= 65
                and 12 <= component_height <= 60
                and 0.10 <= fill <= 0.90
                and 0.12 <= ratio <= 3.5
            ):
                components.append(
                    (
                        min_x,
                        min_y,
                        component_width,
                        component_height,
                        area,
                        sum_x / area,
                        sum_y / area,
                    )
                )

    rows: list[list[tuple[int, int, int, int, int, float, float]]] = []
    for component in sorted(components, key=lambda item: item[6]):
        best_row: list[tuple[int, int, int, int, int, float, float]] | None = None
        best_distance = float("inf")
        for row in rows:
            row_center = float(np.median([item[6] for item in row]))
            row_height = float(np.median([item[3] for item in row]))
            distance = abs(component[6] - row_center)
            if distance <= max(8.0, min(row_height, component[3]) * 0.38) and distance < best_distance:
                best_row = row
                best_distance = distance
        if best_row is None:
            rows.append([component])
        else:
            best_row.append(component)

    boxes: list[tuple[int, int, int, int]] = []
    for row in rows:
        if len(row) < 3:
            continue
        left = min(item[0] for item in row)
        top = min(item[1] for item in row)
        right = max(item[0] + item[2] for item in row)
        bottom = max(item[1] + item[3] for item in row)
        median_height = float(np.median([item[3] for item in row]))
        if right - left < median_height * 2.2 or right - left > median_height * 14.0:
            continue
        ordered = sorted(row, key=lambda item: item[0])
        gaps = [
            ordered[index + 1][0] - (ordered[index][0] + ordered[index][2])
            for index in range(len(ordered) - 1)
        ]
        if gaps and np.percentile(gaps, 80) > median_height * 1.25:
            continue
        box = (max(0, left - 5), max(0, top - 5), min(width, right + 5), min(height, bottom + 5))
        density = float(dark[box[1] : box[3], box[0] : box[2]].mean())
        if 0.07 <= density <= 0.62:
            boxes.append(box)
    return boxes


def _rebuild_text_rows(
    image: Image.Image,
    reference: Image.Image,
    *,
    core_cutoff: float = 145.0,
    background_size: int = 15,
) -> Image.Image:
    """Re-render detected text rows with one ink edge and no gray halo stack."""
    target = image.convert("RGB")
    guide = reference.convert("RGB").resize(target.size, Image.Resampling.LANCZOS, reducing_gap=3.0)
    boxes = _detect_text_rows(guide)
    if not boxes:
        return target
    output = np.asarray(target, dtype=np.float32).copy()
    guide_arr = np.asarray(guide, dtype=np.float32)
    filter_size = max(3, background_size | 1)
    for box in boxes:
        row_height = max(12, box[3] - box[1])
        margin_x = max(18, round(row_height * 0.45))
        margin_y = max(10, round(row_height * 0.24))
        left = max(0, box[0] - margin_x)
        top = max(0, box[1] - margin_y)
        right = min(target.width, box[2] + margin_x)
        bottom = min(target.height, box[3] + margin_y)
        guide_roi = guide_arr[top:bottom, left:right]
        target_roi = output[top:bottom, left:right]
        guide_luma = guide_roi[..., 0] * 0.299 + guide_roi[..., 1] * 0.587 + guide_roi[..., 2] * 0.114
        guide_chroma = guide_roi.max(axis=2) - guide_roi.min(axis=2)
        neutral_ink = guide_chroma < 38.0
        solid_core = (guide_luma < core_cutoff - 20.0) & neutral_ink
        core_image = Image.fromarray(np.uint8(solid_core) * 255, "L")

        guide_image = Image.fromarray(np.uint8(np.clip(guide_roi, 0.0, 255.0)), "RGB")
        background = np.asarray(
            guide_image.filter(ImageFilter.MaxFilter(max(filter_size, 31))).filter(ImageFilter.GaussianBlur(3.2)),
            dtype=np.float32,
        )
        paper_mask = (guide_luma > 200.0) & (guide_chroma < 14.0)
        if np.any(paper_mask):
            paper_color = np.median(guide_roi[paper_mask], axis=0)
            background_color = np.median(background.reshape(-1, 3), axis=0)
            background = np.clip(background + paper_color - background_color, 0.0, 255.0)
        # Keep only the original antialias pixels touching a solid black core.
        # The steep 33-level transition removes the lighter repeated shadows,
        # while the 3x3 support limits the transition to a single pixel.
        supported_edge = np.asarray(core_image.filter(ImageFilter.MaxFilter(3)), dtype=np.float32) / 255.0
        ink_alpha = np.clip((core_cutoff + 13.0 - guide_luma) / 33.0, 0.0, 1.0)
        ink_alpha *= supported_edge * neutral_ink
        core_rgb = np.repeat(np.minimum(guide_luma, 70.0)[..., None], 3, axis=2)
        rendered = background * (1.0 - ink_alpha[..., None]) + core_rgb * ink_alpha[..., None]
        feather = max(5, min(12, round(row_height * 0.18)))
        distances_x = np.minimum(np.arange(right - left), np.arange(right - left)[::-1]).astype(np.float32)
        distances_y = np.minimum(np.arange(bottom - top), np.arange(bottom - top)[::-1]).astype(np.float32)
        patch_alpha = np.clip(
            np.minimum(distances_y[:, None], distances_x[None, :]) / feather,
            0.0,
            1.0,
        )
        output[top:bottom, left:right] = (
            target_roi * (1.0 - patch_alpha[..., None]) + rendered * patch_alpha[..., None]
        )

    return Image.fromarray(np.uint8(np.clip(output, 0.0, 255.0)), "RGB")


def _smart_content_cleaning(image: Image.Image, settings: ClaritySettings) -> Image.Image:
    """Enhance line art conservatively while preserving the resized source canvas."""
    original = image.convert("RGB")
    arr = np.asarray(original).astype(np.float32)
    luma = arr[..., 0] * 0.299 + arr[..., 1] * 0.587 + arr[..., 2] * 0.114
    chroma = arr.max(axis=2) - arr.min(axis=2)
    line_mask, line_context = _line_context_mask(original)

    cleaned_arr = arr.copy()
    if settings.denoise:
        # Smooth bright, low-chroma noise only where artwork is locally dense.
        # The replacement is a local median, so pale green/gray tones are
        # retained instead of being converted to white.
        artwork = _dense_artwork_mask(original)
        # A local high-percentile estimate reconstructs the light paper tone
        # behind gray compression speckles more effectively than a blur.
        denoised = np.asarray(original.filter(ImageFilter.MaxFilter(size=13))).astype(np.float32)
        denoised_luma = denoised[..., 0] * 0.299 + denoised[..., 1] * 0.587 + denoised[..., 2] * 0.114
        denoised_chroma = denoised.max(axis=2) - denoised.min(axis=2)
        local_color = np.asarray(original.filter(ImageFilter.GaussianBlur(radius=15.0))).astype(np.float32)
        local_chroma = local_color.max(axis=2) - local_color.min(axis=2)
        # Clean only pixels whose local neighborhood is also a bright neutral
        # tone. This protects pale colored fills and the antialiasing of text.
        neutral_paper = (
            (chroma <= 14.0)
            & (denoised_chroma <= 14.0)
            & (local_chroma <= 3.0)
            & (denoised_luma >= 205.0)
        )
        speckle_alpha = np.clip((luma - 182.0) / 48.0, 0.0, 1.0) * neutral_paper * artwork * 0.9
        cleaned_arr = arr * (1.0 - speckle_alpha[..., None]) + denoised * speckle_alpha[..., None]

    cleaned = Image.fromarray(np.clip(cleaned_arr, 0, 255).astype(np.uint8), "RGB")
    sharpened = _sharpen_luma(cleaned, settings)
    sharpened_arr = np.asarray(sharpened).astype(np.float32)

    # Apply low-strength luminance sharpening only to actual dark strokes and
    # their immediate anti-aliased edge. No broad content mask is used.
    line_strength = np.clip((195.0 - luma) / 100.0, 0.0, 1.0)
    line_alpha = line_strength * line_mask
    line_alpha += line_strength * line_context * 0.18
    line_alpha = np.clip(line_alpha, 0.0, 0.72)
    final_arr = cleaned_arr * (1.0 - line_alpha[..., None]) + sharpened_arr * line_alpha[..., None]
    return Image.fromarray(np.clip(final_arr, 0, 255).astype(np.uint8), "RGB")


def _merge_v10_with_source_detail(
    v10_image: Image.Image,
    source: Image.Image,
    settings: ClaritySettings,
) -> Image.Image:
    """Keep the v10 image intact and clean only detected text rows."""
    v10_image = v10_image.convert("RGB")
    reference = ImageOps.exif_transpose(source).convert("RGB").resize(
        v10_image.size,
        Image.Resampling.LANCZOS,
        reducing_gap=3.0,
    )
    if not settings.clean_background:
        return v10_image.copy()
    # The first-stage v10 result is the untouched canvas for every non-text
    # pixel. The source is used only as a guide to recover the text ink.
    return _rebuild_text_rows(v10_image, reference)


def _recover_v10_lines(
    image: Image.Image,
    settings: ClaritySettings,
    detail_reference: Image.Image | None,
) -> Image.Image:
    """Rebuild v10 output with source lines while keeping the outer canvas."""
    if detail_reference is None:
        return _smart_content_cleaning(image, settings) if settings.clean_background else _foreground_preserving_clean(image, settings)
    return _merge_v10_with_source_detail(image, detail_reference, settings)


def _restore_regions(
    source_upscaled: Image.Image,
    processed: Image.Image,
    regions: Iterable[tuple[int, int, int, int]],
    x_scale: float,
    y_scale: float,
    feather: int = 20,
) -> Image.Image:
    """Restore original-background rectangles selected in source-image pixels."""
    from PIL import ImageDraw

    boxes: list[tuple[int, int, int, int]] = []
    for x1, y1, x2, y2 in regions:
        box = (
            max(0, round(min(x1, x2) * x_scale)),
            max(0, round(min(y1, y2) * y_scale)),
            min(source_upscaled.width, round(max(x1, x2) * x_scale)),
            min(source_upscaled.height, round(max(y1, y2) * y_scale)),
        )
        if box[2] > box[0] and box[3] > box[1]:
            boxes.append(box)
    if not boxes:
        return processed

    mask = Image.new("L", processed.size, 0)
    draw = ImageDraw.Draw(mask)
    for box in boxes:
        draw.rectangle(box, fill=255)
    mask = mask.filter(ImageFilter.GaussianBlur(radius=max(0, feather)))
    return Image.composite(source_upscaled, processed, mask)


def process_image(
    image: Image.Image,
    settings: ClaritySettings,
    background_regions: Iterable[tuple[int, int, int, int]] = (),
    postprocess_mode: str = POSTPROCESS_ORIGINAL,
    detail_reference: Image.Image | None = None,
) -> Image.Image:
    """Upscale first, then clean/sharpen. Regions use source-image coordinates."""
    if postprocess_mode not in POSTPROCESS_MODES:
        raise ValueError(f"unsupported postprocess mode: {postprocess_mode}")
    source = ImageOps.exif_transpose(image).convert("RGB")
    upscaled, x_scale, y_scale = resize_first(source, settings.max_dimension)
    if postprocess_mode == POSTPROCESS_OPTIMIZED and detail_reference is not None:
        # v10 uses integer 50% dimensions, so its restored aspect ratio can be
        # one pixel narrower than the source (for example 788x798 vs 789x798).
        # Correct that before rebuilding text; resizing afterwards would add
        # fresh gray contour bands around the cleaned black characters.
        target_size = resize_first(
            ImageOps.exif_transpose(detail_reference).convert("RGB"),
            settings.max_dimension,
        )[0].size
        if upscaled.size != target_size:
            upscaled = upscaled.resize(target_size, Image.Resampling.LANCZOS, reducing_gap=3.0)
            x_scale = upscaled.width / source.width
            y_scale = upscaled.height / source.height
    if postprocess_mode == POSTPROCESS_OPTIMIZED:
        processed = _recover_v10_lines(upscaled, settings, detail_reference)
    elif settings.clean_background:
        processed = _smart_content_cleaning(upscaled, settings)
    else:
        processed = _foreground_preserving_clean(upscaled, settings)
    processed = _restore_regions(upscaled, processed, background_regions, x_scale, y_scale)
    return processed


def save_image(image: Image.Image, output_path: Path, output_format: str = "png", jpeg_quality: int = 95) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fmt = output_format.lower().lstrip(".")
    if fmt == "same":
        fmt = output_path.suffix.lower().lstrip(".") or "png"
    if fmt in {"jpg", "jpeg", "jfif"}:
        image.convert("RGB").save(output_path, "JPEG", quality=max(1, min(100, jpeg_quality)), subsampling=0, optimize=True)
    elif fmt == "webp":
        image.convert("RGB").save(output_path, "WEBP", quality=max(1, min(100, jpeg_quality)), method=6)
    elif fmt == "bmp":
        image.convert("RGB").save(output_path, "BMP")
    elif fmt in {"tif", "tiff"}:
        image.convert("RGB").save(output_path, "TIFF", compression="tiff_deflate")
    else:
        image.convert("RGB").save(output_path, "PNG", optimize=True, compress_level=7)


def iter_image_files(input_dir: Path) -> list[Path]:
    """Return supported images recursively, in stable path order."""
    return sorted(
        (path for path in input_dir.rglob("*") if path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS),
        key=lambda path: path.as_posix().lower(),
    )


def iter_text_files(input_dir: Path) -> list[Path]:
    """Return .txt files recursively, in stable path order."""
    return sorted(
        (path for path in input_dir.rglob("*") if path.is_file() and path.suffix.lower() == ".txt"),
        key=lambda path: path.as_posix().lower(),
    )


def copy_text_files(input_dir: Path, output_dir: Path) -> tuple[int, list[str]]:
    """Copy TXT sidecar files to matching relative paths without altering content."""
    copied = 0
    errors: list[str] = []
    for source_path in iter_text_files(input_dir):
        destination = output_dir / source_path.relative_to(input_dir)
        try:
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source_path, destination)
            copied += 1
        except Exception as exc:
            errors.append(f"{source_path}: {exc}")
    return copied, errors


def _batch_output_path(
    source_path: Path,
    input_dir: Path,
    output_dir: Path,
    output_format: str,
    overwrite: bool,
) -> Path:
    relative = source_path.relative_to(input_dir)
    if overwrite:
        # Overwrite mode always keeps the original extension. This prevents a
        # PNG/JPEG format mismatch from leaving an unprocessed original file.
        return source_path
    target = output_dir / relative
    fmt = output_format.lower().lstrip(".")
    if fmt == "png":
        return target.with_suffix(".png")
    if fmt in {"jpg", "jpeg"}:
        return target.with_suffix(".jpg")
    if fmt == "webp":
        return target.with_suffix(".webp")
    return target


def process_folder(
    input_dir: Path,
    output_dir: Path | None,
    settings: ClaritySettings,
    *,
    overwrite: bool = False,
    output_format: str = "png",
    progress: Callable[[int, int, Path, Path | None, str | None], None] | None = None,
) -> tuple[int, int, int, list[str]]:
    """Process every supported image below input_dir, preserving subfolders."""
    input_dir = input_dir.resolve()
    if not input_dir.is_dir():
        raise NotADirectoryError(input_dir)
    if not overwrite and output_dir is None:
        raise ValueError("output_dir is required when overwrite is False")
    output_root = input_dir if overwrite else output_dir.resolve()  # type: ignore[union-attr]
    if not overwrite and (output_root == input_dir or input_dir in output_root.parents):
        raise ValueError("output_dir must be outside input_dir to avoid recursive reprocessing")
    files = iter_image_files(input_dir)
    completed = 0
    failed = 0
    errors: list[str] = []
    for index, source_path in enumerate(files, start=1):
        try:
            result = process_image(open_image(source_path), settings)
            destination = _batch_output_path(source_path, input_dir, output_root, output_format, overwrite)
            save_format = "same" if overwrite else output_format
            save_image(result, destination, save_format, settings.jpeg_quality)
            completed += 1
            if progress is not None:
                progress(index, len(files), source_path, destination, None)
        except Exception as exc:  # keep the batch moving when one file is bad
            failed += 1
            message = f"{source_path}: {exc}"
            errors.append(message)
            if progress is not None:
                progress(index, len(files), source_path, None, message)
    copied_text = 0
    if not overwrite:
        copied_text, copy_errors = copy_text_files(input_dir, output_root)
        errors.extend(copy_errors)
        failed += len(copy_errors)
    return completed, failed, copied_text, errors


def _load_line_pressure_batch_module():
    # PyInstaller places hidden-import modules in the embedded archive rather
    # than next to image_clarity.py. Try that copy first for packaged runs.
    try:
        return importlib.import_module("batch_v10_01_text")
    except Exception as embedded_error:
        embedded_import_error = embedded_error

    local_dir = Path(__file__).resolve().parent
    external_dir = local_dir.parent / "LinePressureImageTool"
    tool_dir = local_dir if (local_dir / "batch_v10_01_text.py").is_file() else external_dir
    module_path = tool_dir / "batch_v10_01_text.py"
    if not module_path.is_file():
        raise FileNotFoundError(
            f"缺少第一步批处理模块：{module_path}；内置模块加载失败：{embedded_import_error}"
        )
    tool_dir_text = str(tool_dir)
    if tool_dir_text not in sys.path:
        sys.path.insert(0, tool_dir_text)
    import batch_v10_01_text

    return batch_v10_01_text


def process_two_stage_folder(
    input_dir: Path,
    output_dir: Path | None,
    settings: ClaritySettings,
    *,
    overwrite: bool = False,
    output_format: str = "png",
    postprocess_mode: str = POSTPROCESS_ORIGINAL,
    progress: PipelineProgress | None = None,
) -> tuple[int, int, int, list[str]]:
    """Run the original v10_01_text, then a selected clarity postprocess."""
    input_dir = input_dir.resolve()
    if not input_dir.is_dir():
        raise NotADirectoryError(input_dir)
    if not overwrite and output_dir is None:
        raise ValueError("output_dir is required when overwrite is False")
    output_root = input_dir if overwrite else output_dir.resolve()  # type: ignore[union-attr]
    if not overwrite and (output_root == input_dir or input_dir in output_root.parents):
        raise ValueError("output_dir must be outside input_dir to avoid recursive reprocessing")

    if postprocess_mode not in POSTPROCESS_MODES:
        raise ValueError(f"unsupported postprocess mode: {postprocess_mode}")
    line_pressure_batch = _load_line_pressure_batch_module()
    errors: list[str] = []
    completed = 0
    failed = 0

    with tempfile.TemporaryDirectory(prefix="image_pipeline_v10_01_text_") as temporary:
        temporary_dir = Path(temporary)

        def stage_one_progress(
            index: int,
            total: int,
            source: Path,
            destination: Path | None,
            error: str | None,
        ) -> None:
            if progress is not None:
                progress(LINE_PRESSURE_METHOD, index, total, source, destination, error)

        first_stage = line_pressure_batch.process_folder(
            input_dir,
            temporary_dir,
            method=LINE_PRESSURE_METHOD,
            copy_text=False,
            temporary_names=True,
            progress=stage_one_progress,
        )
        failed += first_stage.failed
        errors.extend(first_stage.errors)
        successful_items = [item for item in first_stage.items if item.destination is not None and item.error is None]

        for index, item in enumerate(successful_items, start=1):
            source_path = item.source
            intermediate_path = item.destination
            try:
                result = process_image(
                    open_image(intermediate_path),
                    settings,
                    postprocess_mode=postprocess_mode,
                    detail_reference=(open_image(source_path) if postprocess_mode == POSTPROCESS_OPTIMIZED else None),
                )
                destination = _batch_output_path(source_path, input_dir, output_root, output_format, overwrite)
                save_format = "same" if overwrite else output_format
                save_image(result, destination, save_format, settings.jpeg_quality)
                completed += 1
                if progress is not None:
                    progress("clarity", index, len(successful_items), source_path, destination, None)
            except Exception as exc:
                failed += 1
                message = f"{source_path}: {exc}"
                errors.append(message)
                if progress is not None:
                    progress("clarity", index, len(successful_items), source_path, None, message)

    copied_text = 0
    if not overwrite:
        copied_text, copy_errors = copy_text_files(input_dir, output_root)
        errors.extend(copy_errors)
        failed += len(copy_errors)
    return completed, failed, copied_text, errors


def parse_region(value: str) -> tuple[int, int, int, int]:
    parts = [int(part.strip()) for part in value.split(",")]
    if len(parts) != 4:
        raise argparse.ArgumentTypeError("region must be x1,y1,x2,y2")
    return parts[0], parts[1], parts[2], parts[3]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="先放大、再清晰化的图片工具。")
    parser.add_argument("input", type=Path, help="输入图片或文件夹路径")
    parser.add_argument("-o", "--output", type=Path, help="输出图片路径或新输出文件夹")
    parser.add_argument("--max-size", type=int, default=798, help="输出最长边，默认 798；宽高均不超过该值")
    parser.add_argument("--clean-background", action="store_true", help="清理浅灰背景；默认保留原图背景")
    parser.add_argument("--region", type=parse_region, action="append", default=[], help="保留原图背景区域：x1,y1,x2,y2，可重复")
    parser.add_argument("--sharpen", type=int, default=50, help="锐化强度，默认 50")
    parser.add_argument("--contrast", type=float, default=1.015, help="线条对比度，默认 1.015")
    parser.add_argument("--format", choices=["png", "jpeg", "webp", "same"], default="png")
    parser.add_argument("--quality", type=int, default=95, help="JPEG/WebP 质量")
    parser.add_argument("--no-denoise", action="store_true", help="关闭轻度去噪")
    parser.add_argument("--overwrite", action="store_true", help="文件夹模式下覆盖原文件")
    parser.add_argument("--clarity-only", action="store_true", help="仅执行清晰化，跳过第一步 v10_01_text")
    parser.add_argument(
        "--postprocess",
        choices=POSTPROCESS_MODES,
        default=POSTPROCESS_ORIGINAL,
        help="原版 v10_01_text 后的清晰化方式；默认 original",
    )
    args = parser.parse_args(argv)

    settings = ClaritySettings(
        max_dimension=args.max_size,
        sharpen_percent=args.sharpen,
        contrast=args.contrast,
        clean_background=args.clean_background,
        denoise=not args.no_denoise,
        jpeg_quality=args.quality,
    )
    if args.input.is_dir():
        if args.overwrite:
            output_dir = None
        else:
            output_dir = args.output or args.input.with_name(f"{args.input.name}_clarity")
        folder_processor = process_folder if args.clarity_only else process_two_stage_folder
        processor_kwargs = {
            "overwrite": args.overwrite,
            "output_format": "same" if args.overwrite else args.format,
        }
        if not args.clarity_only:
            processor_kwargs["postprocess_mode"] = args.postprocess
        completed, failed, copied_text, errors = folder_processor(
            args.input,
            output_dir,
            settings,
            **processor_kwargs,
        )
        mode = "仅清晰化" if args.clarity_only else f"v10_01_text + {args.postprocess} 清晰化"
        print(f"{mode}：图片完成 {completed} 张，失败 {failed} 项，TXT 复制 {copied_text} 个")
        for error in errors:
            print(f"失败：{error}")
        return 0 if failed == 0 else 2

    output = args.output or args.input.with_name(f"{args.input.stem}_clarity.png")
    result = process_image(open_image(args.input), settings, args.region)
    save_image(result, output, args.format, args.quality)
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
