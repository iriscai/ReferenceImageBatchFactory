from __future__ import annotations

import argparse
import shutil
import zlib
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import numpy as np
from PIL import Image, ImageOps

import naturalize_jfif_small_sharp_v10 as naturalize_v10


IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".jfif", ".webp", ".bmp", ".tif", ".tiff"}
METHOD_KEY = "v10_01_text"
VARIANT_NAME = "v10_01_text_overlay"
VARIANT = next(variant for variant in naturalize_v10.VARIANTS if variant.name == VARIANT_NAME)


@dataclass(slots=True)
class BatchItem:
    source: Path
    destination: Path | None
    error: str | None = None


@dataclass(slots=True)
class BatchResult:
    total: int
    completed: int
    failed: int
    copied_text: int
    items: list[BatchItem]
    errors: list[str]


ProgressCallback = Callable[[int, int, Path, Path | None, str | None], None]


def iter_image_files(input_dir: Path) -> list[Path]:
    return sorted(
        (path for path in input_dir.rglob("*") if path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS),
        key=lambda path: path.as_posix().lower(),
    )


def iter_text_files(input_dir: Path) -> list[Path]:
    return sorted(
        (path for path in input_dir.rglob("*") if path.is_file() and path.suffix.lower() == ".txt"),
        key=lambda path: path.as_posix().lower(),
    )


def _method_seed(source_path: Path) -> int:
    data = f"{source_path.as_posix()}::{METHOD_KEY}".encode("utf-8", errors="ignore")
    return 2026070610 + zlib.crc32(data)


def _output_path(source_path: Path, input_dir: Path, output_dir: Path, temporary_names: bool) -> Path:
    relative = source_path.relative_to(input_dir)
    if temporary_names:
        # Flatten temporary files to avoid Windows path-length failures when
        # the source has deeply nested, long Chinese directory names.
        identity = zlib.crc32(relative.as_posix().encode("utf-8", errors="ignore"))
        short_name = relative.name[:80]
        return output_dir / f"{identity:08x}_{short_name}.jpg"
    return output_dir / relative.parent / f"{relative.stem}_{VARIANT_NAME}.jpg"


def process_image(source_path: Path) -> Image.Image:
    with Image.open(source_path) as opened:
        source = ImageOps.exif_transpose(opened).convert("RGB")
    rng = np.random.default_rng(_method_seed(source_path))
    return naturalize_v10.process_variant(source, VARIANT, rng)


def save_jpeg(image: Image.Image, destination: Path, quality: int = 90) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    image.convert("RGB").save(destination, "JPEG", quality=quality, subsampling=2, optimize=True)


def copy_text_files(input_dir: Path, output_dir: Path) -> tuple[int, list[str]]:
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


def process_folder(
    input_dir: Path,
    output_dir: Path,
    *,
    method: str = METHOD_KEY,
    copy_text: bool = True,
    temporary_names: bool = False,
    progress: ProgressCallback | None = None,
) -> BatchResult:
    """Recursively process a folder using the exact v10_01_text method."""
    if method != METHOD_KEY:
        raise ValueError(f"unsupported method: {method}; expected {METHOD_KEY}")
    input_dir = input_dir.resolve()
    output_dir = output_dir.resolve()
    if not input_dir.is_dir():
        raise NotADirectoryError(input_dir)
    if output_dir == input_dir or input_dir in output_dir.parents:
        raise ValueError("output_dir must be outside input_dir")

    files = iter_image_files(input_dir)
    items: list[BatchItem] = []
    errors: list[str] = []
    completed = 0
    failed = 0
    for index, source_path in enumerate(files, start=1):
        destination = _output_path(source_path, input_dir, output_dir, temporary_names)
        try:
            save_jpeg(process_image(source_path), destination)
            completed += 1
            items.append(BatchItem(source_path, destination))
            if progress is not None:
                progress(index, len(files), source_path, destination, None)
        except Exception as exc:
            failed += 1
            message = f"{source_path}: {exc}"
            errors.append(message)
            items.append(BatchItem(source_path, None, message))
            if progress is not None:
                progress(index, len(files), source_path, None, message)

    copied_text = 0
    if copy_text:
        copied_text, text_errors = copy_text_files(input_dir, output_dir)
        errors.extend(text_errors)
        failed += len(text_errors)
    return BatchResult(len(files), completed, failed, copied_text, items, errors)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="批量执行 LinePressureImageTool v10_01_text。")
    parser.add_argument("input", type=Path, help="输入图片文件夹")
    parser.add_argument("-o", "--output", type=Path, required=True, help="输出 JPG 文件夹")
    parser.add_argument("--method", choices=[METHOD_KEY], default=METHOD_KEY)
    parser.add_argument("--no-copy-txt", action="store_true", help="不复制 TXT 文件")
    args = parser.parse_args(argv)

    result = process_folder(
        args.input,
        args.output,
        method=args.method,
        copy_text=not args.no_copy_txt,
    )
    print(
        f"v10_01_text 完成 {result.completed}/{result.total} 张，"
        f"失败 {result.failed} 项，TXT 复制 {result.copied_text} 个"
    )
    for error in result.errors:
        print(f"失败：{error}")
    return 0 if result.failed == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
