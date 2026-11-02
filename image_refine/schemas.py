# -*- coding: utf-8 -*-
"""参数模型：处理方案（Plan）的完整定义与校验。"""
import re

from pydantic import BaseModel, Field, field_validator

# 画布比例（值为 w/h）；original 表示跟随原图
CANVAS_RATIOS = ["original", "1:1", "4:5", "3:4", "2:3", "9:16", "16:9", "3:2"]
# 裁切基准：卡片在画布中的对齐方式（放大溢出画布时决定保留哪一侧）
CROP_ANCHORS = ["center", "top", "bottom", "left", "right"]

_COLOR_RE = re.compile(r"^#[0-9a-fA-F]{6}$")


class Plan(BaseModel):
    """一次精修的全部参数，前后端与持久化共用同一份结构。"""

    # 画布与背景
    canvas_ratio: str = "4:5"
    bg_blur_enabled: bool = True
    bg_blur_strength: int = Field(35, ge=0, le=200)      # 背景虚化强度（px）
    # 构图与导出
    zoom: int = Field(1, ge=0, le=100)                   # 构图放大（%）
    crop_anchor: str = "center"
    export_quality: int = Field(100, ge=40, le=100)      # 导出质量（%，对 JPG/WebP 生效）
    # 边框
    border_enabled: bool = True
    border_width: int = Field(11, ge=0, le=100)          # px
    border_color: str = "#FFFFFF"
    # 圆角
    radius_enabled: bool = True
    radius: int = Field(14, ge=0, le=300)                # px
    # 阴影
    shadow_enabled: bool = True
    shadow_strength: int = Field(40, ge=0, le=100)       # %
    # 光影色彩
    color_enabled: bool = True
    brightness: int = Field(0, ge=-100, le=100)
    contrast: int = Field(0, ge=-100, le=100)
    saturation: int = Field(0, ge=-100, le=100)
    warmth: int = Field(0, ge=-100, le=100)
    # 质感
    texture_enabled: bool = True
    grain: int = Field(4, ge=0, le=60)                   # 颗粒
    sharpness: int = Field(5, ge=0, le=30)               # 锐度

    @field_validator("canvas_ratio")
    @classmethod
    def _check_ratio(cls, v: str) -> str:
        if v not in CANVAS_RATIOS:
            raise ValueError(f"不支持的画布比例：{v}")
        return v

    @field_validator("crop_anchor")
    @classmethod
    def _check_anchor(cls, v: str) -> str:
        if v not in CROP_ANCHORS:
            raise ValueError(f"不支持的裁切基准：{v}")
        return v

    @field_validator("border_color")
    @classmethod
    def _check_color(cls, v: str) -> str:
        if not _COLOR_RE.match(v or ""):
            raise ValueError("边框颜色需为 #RRGGBB 格式")
        return v.upper()


DEFAULT_PLAN = Plan().model_dump()
