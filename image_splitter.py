from __future__ import annotations

import argparse
import re
import shutil
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable

SUPPORTED_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff"}


class ImageSplitError(RuntimeError):
    pass


@dataclass(frozen=True)
class SplitConfig:
    input_dir: Path
    columns: int = 2
    rows: int = 3
    recursive: bool = True
    overwrite: bool = True
    copy_before_split: bool = True
    split_mode: str = "fixed"
    border_trim: int = 12

    def normalized(self) -> "SplitConfig":
        columns = max(1, min(int(self.columns), 20))
        rows = max(1, min(int(self.rows), 20))
        split_mode = str(self.split_mode or "fixed").strip().lower()
        if split_mode not in {"fixed", "smart", "gutter"}:
            split_mode = "fixed"
        border_trim = max(0, min(int(self.border_trim), 50))
        return SplitConfig(
            input_dir=Path(self.input_dir),
            columns=columns,
            rows=rows,
            recursive=bool(self.recursive),
            overwrite=bool(self.overwrite),
            copy_before_split=bool(self.copy_before_split),
            split_mode=split_mode,
            border_trim=border_trim,
        )


@dataclass(frozen=True)
class SplitSummary:
    working_dir: Path
    source_count: int
    success_count: int
    skipped_count: int
    failed_count: int
    saved_count: int
    stopped: bool = False


def supported_suffixes() -> set[str]:
    return set(SUPPORTED_SUFFIXES)


def working_copy_dir(input_dir: Path) -> Path:
    source = Path(input_dir)
    base = source.with_name(f"{source.name}_切图")
    target = base
    suffix = 2
    while target.exists():
        target = source.with_name(f"{source.name}_切图_{suffix}")
        suffix += 1
    return target


def is_split_piece(path: Path) -> bool:
    return bool(re.search(r"_切图_\d+$", path.stem))


def image_sources(input_dir: Path, recursive: bool) -> list[Path]:
    root = Path(input_dir)
    iterator: Iterable[Path] = root.rglob("*") if recursive else root.iterdir()
    sources = []
    for path in iterator:
        if not path.is_file():
            continue
        if path.suffix.lower() not in SUPPORTED_SUFFIXES:
            continue
        if is_split_piece(path):
            continue
        sources.append(path)
    return sorted(sources, key=lambda item: str(item).lower())


def piece_paths(image_path: Path, count: int) -> list[Path]:
    suffix = image_path.suffix.lower() or ".png"
    return [image_path.with_name(f"{image_path.stem}_切图_{index}{suffix}") for index in range(1, count + 1)]


def fixed_boxes(width: int, height: int, rows: int, columns: int) -> list[tuple[int, int, int, int]]:
    boxes = []
    for row in range(rows):
        top = round(row * height / rows)
        bottom = round((row + 1) * height / rows)
        for column in range(columns):
            left = round(column * width / columns)
            right = round((column + 1) * width / columns)
            boxes.append((left, top, right, bottom))
    return boxes


def trim_box(
    box: tuple[int, int, int, int],
    width: int,
    height: int,
    trim: int,
) -> tuple[int, int, int, int]:
    if trim <= 0:
        return box
    left, top, right, bottom = box
    box_width = right - left
    box_height = bottom - top
    safe_trim = min(trim, max(0, (box_width - 2) // 2), max(0, (box_height - 2) // 2))
    if safe_trim <= 0:
        return box
    return (
        max(0, left + safe_trim),
        max(0, top + safe_trim),
        min(width, right - safe_trim),
        min(height, bottom - safe_trim),
    )


def trim_boxes(
    boxes: list[tuple[int, int, int, int]],
    width: int,
    height: int,
    trim: int,
) -> list[tuple[int, int, int, int]]:
    return [trim_box(box, width, height, trim) for box in boxes]


def dark_ratio(values: list[int], dark_limit: int = 90) -> float:
    if not values:
        return 0.0
    return sum(value <= dark_limit for value in values) / len(values)


def detected_edge_trim(piece, max_trim: int) -> tuple[int, int, int, int]:
    if max_trim <= 0:
        return (0, 0, 0, 0)
    gray = piece.convert("L")
    width, height = gray.size
    if width <= 2 or height <= 2:
        return (0, 0, 0, 0)
    pixels = gray.load()
    limit_x = min(max_trim, max(0, (width - 2) // 2))
    limit_y = min(max_trim, max(0, (height - 2) // 2))
    threshold = 0.72

    left = 0
    for x in range(limit_x):
        if dark_ratio([pixels[x, y] for y in range(height)]) >= threshold:
            left = x + 1
        else:
            break

    right = 0
    for offset in range(limit_x):
        x = width - 1 - offset
        if dark_ratio([pixels[x, y] for y in range(height)]) >= threshold:
            right = offset + 1
        else:
            break

    top = 0
    for y in range(limit_y):
        if dark_ratio([pixels[x, y] for x in range(width)]) >= threshold:
            top = y + 1
        else:
            break

    bottom = 0
    for offset in range(limit_y):
        y = height - 1 - offset
        if dark_ratio([pixels[x, y] for x in range(width)]) >= threshold:
            bottom = offset + 1
        else:
            break

    return (left, top, right, bottom)


def trim_detected_border_lines(piece, max_trim: int):
    left, top, right, bottom = detected_edge_trim(piece, max_trim)
    if not any((left, top, right, bottom)):
        return piece
    width, height = piece.size
    crop_right = width - right
    crop_bottom = height - bottom
    if crop_right - left < 2 or crop_bottom - top < 2:
        return piece
    return piece.crop((left, top, crop_right, crop_bottom))

def trim_fixed_border(piece, trim: int):
    if trim <= 0:
        return piece
    width, height = piece.size
    safe_trim = min(trim, max(0, (width - 2) // 2), max(0, (height - 2) // 2))
    if safe_trim <= 0:
        return piece
    return piece.crop((safe_trim, safe_trim, width - safe_trim, height - safe_trim))


def profile_clusters(values: list[float], threshold: float, min_width: int) -> list[tuple[int, int]]:
    clusters = []
    start = None
    for index, value in enumerate(values):
        if value >= threshold:
            if start is None:
                start = index
        elif start is not None:
            if index - start >= min_width:
                clusters.append((start, index))
            start = None
    if start is not None and len(values) - start >= min_width:
        clusters.append((start, len(values)))
    return clusters


def merge_close_cuts(cuts: list[tuple[int, int]], gap: int) -> list[tuple[int, int]]:
    if not cuts:
        return []
    merged = [cuts[0]]
    for start, end in cuts[1:]:
        prev_start, prev_end = merged[-1]
        if start - prev_end <= gap:
            merged[-1] = (prev_start, end)
        else:
            merged.append((start, end))
    return merged


def axis_cut_positions(
    profile: list[float],
    length: int,
    threshold: float,
    min_width: int,
    edge_margin: int,
) -> list[tuple[int, int]]:
    raw = profile_clusters(profile, threshold, min_width)
    cuts = []
    for start, end in merge_close_cuts(raw, gap=max(2, min_width)):
        center = (start + end) / 2
        if center < edge_margin or center > length - edge_margin:
            continue
        cuts.append((start, end))
    return cuts


def smart_boxes(image) -> list[tuple[int, int, int, int]]:
    gray = image.convert("L")
    width, height = gray.size
    pixels = gray.tobytes()
    dark_limit = 50
    x_counts = [0] * width
    y_counts = [0] * height

    for y in range(height):
        offset = y * width
        row_count = 0
        for x in range(width):
            if pixels[offset + x] <= dark_limit:
                x_counts[x] += 1
                row_count += 1
        y_counts[y] = row_count

    x_profile = [count / height for count in x_counts]
    y_profile = [count / width for count in y_counts]
    vertical_cuts = axis_cut_positions(
        x_profile,
        width,
        threshold=0.85,
        min_width=1,
        edge_margin=max(12, round(width * 0.04)),
    )
    horizontal_cuts = axis_cut_positions(
        y_profile,
        height,
        threshold=0.85,
        min_width=1,
        edge_margin=max(12, round(height * 0.025)),
    )

    x_edges = [0] + [round((start + end) / 2) for start, end in vertical_cuts] + [width]
    y_edges = [0] + [round((start + end) / 2) for start, end in horizontal_cuts] + [height]
    x_edges = sorted(set(x_edges))
    y_edges = sorted(set(y_edges))

    min_piece_width = max(80, round(width * 0.12))
    min_piece_height = max(80, round(height * 0.08))
    boxes = []
    for top, bottom in zip(y_edges, y_edges[1:]):
        if bottom - top < min_piece_height:
            continue
        for left, right in zip(x_edges, x_edges[1:]):
            if right - left < min_piece_width:
                continue
            boxes.append((left, top, right, bottom))
    return boxes


def gutter_boxes(image, rows: int, columns: int) -> list[tuple[int, int, int, int]]:
    """Split on the white gaps between panels, so unequal cells stay intact.

    A gutter row is almost entirely white, including both outer edges. Rows
    inside a framed panel keep dark borders, so they are not treated as gaps.
    Returns an empty list when the expected gaps cannot be found.
    """
    gray = image.convert("L")
    width, height = gray.size
    if width < 40 or height < 40 or rows < 1 or columns < 1:
        return []
    pixels = gray.tobytes()
    white_limit = 236

    def row_is_gap(y: int) -> bool:
        offset = y * width
        if pixels[offset] < white_limit or pixels[offset + width - 1] < white_limit:
            return False
        white = sum(value >= white_limit for value in pixels[offset:offset + width])
        return white / width >= 0.96

    def column_is_gap(x: int) -> bool:
        white = 0
        for y in range(height):
            if pixels[y * width + x] >= white_limit:
                white += 1
        if white / height < 0.92:
            return False
        return pixels[x] >= white_limit and pixels[(height - 1) * width + x] >= white_limit

    def choose_gaps(flags: list[bool], length: int, parts: int) -> list[tuple[int, int]]:
        if parts <= 1:
            return []
        min_width = 2
        clusters = profile_clusters([1.0 if flag else 0.0 for flag in flags], 1.0, min_width)
        edge_margin = max(8, round(length * 0.04))
        max_width = max(12, round(length * 0.12))
        usable = []
        for start, end in clusters:
            center = (start + end) / 2
            if center < edge_margin or center > length - edge_margin:
                continue
            if end - start > max_width:
                continue
            usable.append((start, end))
        chosen = []
        used = set()
        window = length * 0.22
        for index in range(1, parts):
            target = index * length / parts
            best = None
            best_distance = window
            for cluster_index, (start, end) in enumerate(usable):
                if cluster_index in used:
                    continue
                distance = abs(((start + end) / 2) - target)
                if distance < best_distance:
                    best = cluster_index
                    best_distance = distance
            if best is None:
                return []
            used.add(best)
            chosen.append(usable[best])
        chosen.sort()
        return chosen

    horizontal = choose_gaps([row_is_gap(y) for y in range(height)], height, rows)
    vertical = choose_gaps([column_is_gap(x) for x in range(width)], width, columns)
    if len(horizontal) != max(0, rows - 1) or len(vertical) != max(0, columns - 1):
        return []

    y_edges = [0]
    for start, end in horizontal:
        y_edges.extend((start, end))
    y_edges.append(height)
    x_edges = [0]
    for start, end in vertical:
        x_edges.extend((start, end))
    x_edges.append(width)

    boxes = []
    for top, bottom in zip(y_edges[0::2], y_edges[1::2]):
        if bottom - top < 20:
            return []
        for left, right in zip(x_edges[0::2], x_edges[1::2]):
            if right - left < 20:
                return []
            boxes.append((left, top, right, bottom))
    if len(boxes) != rows * columns:
        return []
    return boxes


def should_fallback_to_fixed(width: int, height: int, boxes: list[tuple[int, int, int, int]], rows: int, columns: int) -> bool:
    if len(boxes) <= 1:
        return True
    expected = rows * columns
    if expected >= 4 and len(boxes) < max(4, expected // 2):
        return True
    aspect = width / height if height else 0
    standard_page = 0.62 <= aspect <= 0.72 and width >= 800 and height >= 1200
    if standard_page and expected == 6 and len(boxes) != 6:
        return True
    return False


def save_piece(piece, target: Path) -> None:
    save_kwargs = {}
    if target.suffix.lower() in {".jpg", ".jpeg"}:
        if piece.mode in {"RGBA", "LA", "P"}:
            piece = piece.convert("RGB")
        save_kwargs = {"quality": 95}
    piece.save(target, **save_kwargs)


def split_image_file(
    image_path: Path,
    rows: int,
    columns: int,
    overwrite: bool,
    split_mode: str = "fixed",
    border_trim: int = 4,
) -> tuple[int, str]:
    try:
        from PIL import Image, ImageOps
    except ImportError as exc:
        raise ImageSplitError("缺少依赖 Pillow，请先执行：pip install pillow") from exc

    with Image.open(image_path) as source:
        image = ImageOps.exif_transpose(source)
        width, height = image.size
        used_mode = split_mode
        boxes = []
        if split_mode == "gutter":
            boxes = gutter_boxes(image, rows, columns)
            if len(boxes) != rows * columns:
                used_mode = "fixed"
                boxes = fixed_boxes(width, height, rows, columns)
        elif split_mode == "smart":
            boxes = smart_boxes(image)
            if should_fallback_to_fixed(width, height, boxes, rows, columns):
                used_mode = "fixed"
                boxes = fixed_boxes(width, height, rows, columns)
        else:
            boxes = fixed_boxes(width, height, rows, columns)
        piece_trim = 0 if used_mode == "gutter" else border_trim
        targets = piece_paths(image_path, len(boxes))
        if not overwrite and all(path.exists() for path in targets):
            image_path.unlink(missing_ok=True)
            return 0, used_mode

        targets[0].parent.mkdir(parents=True, exist_ok=True)
        saved = 0
        for box, target in zip(boxes, targets):
            if target.exists() and not overwrite:
                continue
            piece = trim_fixed_border(image.crop(box), piece_trim)
            save_piece(piece, target)
            saved += 1

    if all(path.exists() for path in targets):
        image_path.unlink(missing_ok=True)
    return saved, used_mode


def split_directory(
    config: SplitConfig,
    log: Callable[[str], None] | None = None,
    stop_event: threading.Event | None = None,
) -> SplitSummary:
    config = config.normalized()
    logger = log or (lambda _message: None)
    input_root = config.input_dir
    if not input_root.is_dir():
        raise ImageSplitError("请先选择有效的图片文件夹。")

    if config.copy_before_split:
        working_root = working_copy_dir(input_root)
        logger(f"复制图片文件夹：{input_root} -> {working_root}")
        shutil.copytree(input_root, working_root)
    else:
        working_root = input_root

    if stop_event is not None and stop_event.is_set():
        logger("收到停止请求，未开始切图。")
        return SplitSummary(working_root, 0, 0, 0, 0, 0, stopped=True)

    sources = image_sources(working_root, config.recursive)
    if not sources:
        logger("没有找到可切割图片。")
        return SplitSummary(working_root, 0, 0, 0, 0, 0)

    mode_text = "智能分镜" if config.split_mode == "smart" else f"固定网格 {config.columns} 列 x {config.rows} 行"
    logger(f"开始切割：{len(sources)} 张图片，模式：{mode_text}，处理目录：{working_root}")
    success_count = 0
    skipped_count = 0
    failed_count = 0
    saved_count = 0

    for index, image_path in enumerate(sources, start=1):
        if stop_event is not None and stop_event.is_set():
            logger("收到停止请求，正在结束。")
            return SplitSummary(
                working_root,
                len(sources),
                success_count,
                skipped_count,
                failed_count,
                saved_count,
                stopped=True,
            )
        try:
            saved, used_mode = split_image_file(
                image_path,
                config.rows,
                config.columns,
                config.overwrite,
                config.split_mode,
                config.border_trim,
            )
            if saved == 0:
                skipped_count += 1
                logger(f"跳过：{image_path.name}，切图已存在。")
            else:
                success_count += 1
                saved_count += saved
                label = "智能" if used_mode == "smart" else "固定"
                logger(f"成功：{index}/{len(sources)} {image_path.name} -> {saved} 张（{label}）")
        except Exception as exc:
            failed_count += 1
            logger(f"失败：{image_path.name}：{exc}")

    summary = SplitSummary(
        working_root,
        len(sources),
        success_count,
        skipped_count,
        failed_count,
        saved_count,
    )
    if failed_count:
        logger(f"图片切割结束：成功 {success_count} 张，输出 {saved_count} 张切图，失败 {failed_count} 张。")
        raise ImageSplitError(f"图片切割有 {failed_count} 张失败。")

    logger(f"图片切割完成：成功 {success_count} 张，跳过 {skipped_count} 张，输出 {saved_count} 张切图。")
    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="批量图片切割工具")
    parser.add_argument("input_dir", nargs="?", help="需要切割的图片文件夹")
    parser.add_argument("--columns", "-c", type=int, default=2, help="列数，默认 2")
    parser.add_argument("--rows", "-r", type=int, default=3, help="行数，默认 3")
    parser.add_argument("--smart", action="store_true", help="启用智能分镜切割")
    parser.add_argument("--border-trim", type=int, default=12, help="从每个切片四周统一裁掉的固定像素，默认 12，设为 0 可保留边框")
    parser.add_argument("--no-recursive", action="store_true", help="不递归读取子文件夹")
    parser.add_argument("--no-overwrite", action="store_true", help="不覆盖已存在切图")
    parser.add_argument("--in-place", action="store_true", help="直接处理原文件夹，不复制副本")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not args.input_dir:
        raise SystemExit("请提供图片文件夹路径，或运行：python gui.py")

    config = SplitConfig(
        input_dir=Path(args.input_dir),
        columns=args.columns,
        rows=args.rows,
        recursive=not args.no_recursive,
        overwrite=not args.no_overwrite,
        copy_before_split=not args.in_place,
        split_mode="smart" if args.smart else "fixed",
        border_trim=args.border_trim,
    )
    split_directory(config, log=print)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
