# -*- coding: utf-8 -*-
"""处理方案预设：内置预设 + 自定义方案持久化（data/presets.json）。"""
from __future__ import annotations

import json
import threading
from pathlib import Path

from image_refine.schemas import DEFAULT_PLAN, Plan

_DATA_DIR = Path(__file__).resolve().parent.parent / "data"
_CUSTOM_FILE = _DATA_DIR / "presets.json"

# 内置预设：在默认方案基础上覆盖部分参数
BUILTIN_PRESETS: dict[str, dict] = {
    "清透": {
        "canvas_ratio": "4:5", "zoom": 2,
        "bg_blur_strength": 30, "border_width": 10, "radius": 16, "shadow_strength": 30,
        "brightness": 8, "contrast": 10, "saturation": 8, "warmth": -4,
        "grain": 0, "sharpness": 6, "export_quality": 95,
    },
    "纸感": {
        "canvas_ratio": "4:5", "zoom": 3,
        "bg_blur_strength": 26, "border_width": 18, "border_color": "#FFFDF6",
        "radius": 8, "shadow_strength": 25,
        "brightness": 10, "contrast": -5, "saturation": -14, "warmth": 14,
        "grain": 16, "sharpness": 2, "export_quality": 95,
    },
    "杂志": {
        "canvas_ratio": "3:4", "zoom": 4,
        "bg_blur_strength": 20, "border_width": 14, "radius_enabled": False,
        "shadow_enabled": False,
        "brightness": 2, "contrast": 16, "saturation": -8,
        "grain": 2, "sharpness": 12, "export_quality": 96,
    },
    "运营贴图": {
        "canvas_ratio": "4:5", "zoom": 2,
        "bg_blur_strength": 45, "border_enabled": False, "radius": 24, "shadow_strength": 55,
        "brightness": 4, "contrast": 8, "saturation": 14, "warmth": 2,
        "grain": 4, "sharpness": 8, "export_quality": 95,
    },
}


def full_plan(overrides: dict) -> dict:
    """补全为完整方案（缺省项取默认值），并过一遍校验。"""
    merged = {**DEFAULT_PLAN, **(overrides or {})}
    return Plan(**merged).model_dump()


class PresetStore:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        _DATA_DIR.mkdir(parents=True, exist_ok=True)
        self._custom: dict[str, dict] = {}
        if _CUSTOM_FILE.exists():
            try:
                self._custom = {
                    name: full_plan(p) for name, p in json.loads(_CUSTOM_FILE.read_text("utf-8")).items()
                }
            except Exception:
                self._custom = {}

    def _flush(self) -> None:
        _CUSTOM_FILE.write_text(
            json.dumps(self._custom, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    def all(self) -> dict:
        with self._lock:
            return {
                "builtin": {k: full_plan(v) for k, v in BUILTIN_PRESETS.items()},
                "custom": dict(self._custom),
                "default": dict(DEFAULT_PLAN),
            }

    def save(self, name: str, plan: dict) -> dict:
        name = (name or "").strip()
        if not name:
            raise ValueError("方案名称不能为空")
        if name in BUILTIN_PRESETS:
            raise ValueError("不能覆盖内置预设，请换一个名称")
        full = full_plan(plan)
        with self._lock:
            self._custom[name] = full
            self._flush()
        return full

    def delete(self, name: str) -> None:
        with self._lock:
            if name not in self._custom:
                raise ValueError("自定义方案不存在")
            del self._custom[name]
            self._flush()


STORE = PresetStore()
