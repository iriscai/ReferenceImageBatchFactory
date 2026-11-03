"""Isolated multi-reference mode. Existing image modes never call this chain."""
from multi_reference_picker import MultiReferencePickerMixin
import concurrent.futures
import copy
import json
import re
import time
from pathlib import Path
import tkinter as tk
from tkinter import ttk, messagebox

GENERATION_MODE_MULTI_REFERENCE = "多参考图生图"
MULTI_REFERENCE_MAX_FRAMES = 12
MULTI_REFERENCE_MAX_SUPPORTING_CAST = 3
MULTI_REFERENCE_CAST_NONE = "无副角色"
MULTI_REFERENCE_ARTICLE_FILENAME = "文章.txt"
MULTI_REFERENCE_DEFAULT_SCENE = "根据本张文案安排相关人物、动作、表情和场景；保持主角色一致。"
GRID_LAYOUT_SINGLE = "单幅"


class MultiReferenceModeMixin(MultiReferencePickerMixin):
    def multi_reference_binding(self, account: dict | None) -> dict:
        """Only this explicit mode reads multi_reference_config."""
        account = account if isinstance(account, dict) else {}
        config = account.get("multi_reference_config") or {}
        label = str(account.get("name") or account.get("account_id") or "账号")
        roles = []
        for role, key in [("background", "background_names"), ("character", "character_names")]:
            for name in self.normalize_multi_reference_names(config.get(key)):
                roles.append({"name": name, "role": role})
        names = [item["name"] for item in roles]
        if not names:
            raise RuntimeError(f"账号「{label}」尚未配置多参考图，请点击“多参考图配置”。")
        if len(set(names)) != len(names):
            raise RuntimeError("同一张参考图不能同时作为背景图和形象图，请明确其用途。")
        paths = []
        first = None
        for item in roles:
            name = item["name"]
            record = self.reference_image_by_name(name)
            if not record or record.get("enabled", True) is False:
                raise RuntimeError(f"账号「{label}」的参考图「{name}」不存在或已停用，请重新配置。")
            path = self.resolve_reference_image_path(record)
            if path is None:
                raise RuntimeError(f"参考图「{name}」文件缺失，请先替换或重新选择。")
            resolved = str(Path(path).resolve())
            if resolved in paths:
                raise RuntimeError(f"参考图「{name}」与其他已选参考图指向同一文件，请去重。")
            paths.append(resolved)
            first = first or record
        first = first or {}
        size = str(config.get("image_size") or "").strip()
        if size:
            if not re.fullmatch(r"[1-9]\d*x[1-9]\d*", size):
                raise RuntimeError("多参考图尺寸须填写宽x高，例如1024x1536，或留空跟随首张背景图。")
            width, height = map(int, size.split("x"))
        else:
            width, height = int(first.get("width") or 0), int(first.get("height") or 0)
        return {"mode": "multi_reference", "name": "、".join(names), "names": names,
                "image_paths": paths, "image_path": paths[0], "reference_roles": roles,
                "width": width, "height": height, "detail": "多参考图独立链路"}

    def multi_reference_binding_display(self, account: dict | None) -> str:
        config = (account or {}).get("multi_reference_config") or {}
        backgrounds = self.normalize_multi_reference_names(config.get("background_names"))
        characters = self.normalize_multi_reference_names(config.get("character_names"))
        return f"{GENERATION_MODE_MULTI_REFERENCE}：背景{len(backgrounds)}张 / 形象{len(characters)}张"

    def render_multi_reference_config_button(self, parent):
        bar = ttk.Frame(parent)
        bar.pack(fill="x", pady=(0, 6))
        ttk.Button(bar, text="多参考图配置…", command=self.open_multi_reference_config).pack(side="left")
        ttk.Label(bar, text="独立配置背景与画风图、人物形象图；仅多参考图生图模式读取。 ").pack(side="left", padx=8)

    def open_multi_reference_config(self):
        return self.open_multi_reference_accounts_window()

    def normalize_multi_reference_names(self, value) -> list[str]:
        """多参考图生图的参考图名单。库里不区分类型，账号只保存参考图管理中的名称。"""
        if isinstance(value, list):
            parts = value
        else:
            text = str(value or "").replace("\n", "、").replace(",", "、").replace("，", "、").replace(";", "、").replace("；", "、")
            parts = text.split("、")
        names = []
        seen = set()
        for part in parts:
            name = str(part or "").strip()
            if name and name not in seen:
                seen.add(name)
                names.append(name)
        return names

    def _multi_reference_compact_map(self, text: str) -> tuple[str, list[int]]:
        """Drop whitespace and remember where each remaining character sits."""
        chars = []
        indexes = []
        for index, char in enumerate(str(text or "")):
            if char.isspace():
                continue
            chars.append(char)
            indexes.append(index)
        return "".join(chars), indexes

    def _multi_reference_beat_title(self, copy: str, index: int) -> str:
        compact, _indexes = self._multi_reference_compact_map(copy)
        compact = compact.strip("。！？!?；;，,、")
        if not compact:
            return f"第{index}张"
        return compact[:18]

    def _multi_reference_order_candidates(self, blocks: list[dict]) -> list[list[dict]]:
        """Appearance order first; unique 场景画面 numbers are the other reading order."""
        appearance = list(blocks)
        candidates = [appearance]
        numbers = [int(item.get("number") or 0) for item in appearance]
        if numbers and len(set(numbers)) == len(numbers):
            ordered = sorted(appearance, key=lambda item: int(item.get("number") or 0))
            if [item.get("number") for item in ordered] != numbers:
                candidates.append(ordered)
        return candidates

    def _align_multi_reference_copy_order(self, body: str, blocks: list[dict]) -> list[dict] | None:
        """Accept this order only when the copies rebuild the body from start to end."""
        body_norm, norm_to_orig = self._multi_reference_compact_map(body)
        if not body_norm:
            return None
        cursor = 0
        spans = []
        for block in blocks:
            piece, _indexes = self._multi_reference_compact_map(block.get("copy") or "")
            if not piece or not body_norm.startswith(piece, cursor):
                return None
            end_index = cursor + len(piece) - 1
            spans.append((norm_to_orig[cursor], norm_to_orig[end_index] + 1, block))
            cursor += len(piece)
        if cursor != len(body_norm):
            return None
        content_starts = [start for start, _end, _block in spans]
        result = []
        for index, (_start, _end, block) in enumerate(spans):
            slice_start = 0 if index == 0 else content_starts[index]
            slice_end = content_starts[index + 1] if index + 1 < len(spans) else len(body)
            copy = body[slice_start:slice_end]
            scene = str(block.get("scene") or "").strip() or MULTI_REFERENCE_DEFAULT_SCENE
            title = str(block.get("title") or "").strip() or self._multi_reference_beat_title(copy, index + 1)
            result.append({"scene_no": index + 1, "title": title, "copy": copy, "scene": scene})
        if "".join(item["copy"] for item in result) != body:
            return None
        return result

    def align_multi_reference_storyboard_copies(self, body: str, blocks: list[dict]) -> list[dict] | None:
        """Return ordered original slices, or None when the answer drops or reorders text."""
        body = str(body or "").replace("\r\n", "\n").replace("\r", "\n").strip()
        if not body or not blocks:
            return None
        for candidate in self._multi_reference_order_candidates(blocks):
            aligned = self._align_multi_reference_copy_order(body, candidate)
            if aligned is not None:
                return aligned
        return None

    def limit_multi_reference_frames(self, frames: list[dict], limit: int = MULTI_REFERENCE_MAX_FRAMES) -> list[dict]:
        """Merge the shortest neighboring pair until the frame count fits the cap."""
        frames = [dict(item) for item in frames]
        limit = max(1, int(limit or MULTI_REFERENCE_MAX_FRAMES))
        while len(frames) > limit:
            pair = min(
                range(len(frames) - 1),
                key=lambda index: len(frames[index]["copy"]) + len(frames[index + 1]["copy"]),
            )
            left, right = frames[pair], frames[pair + 1]
            frames = frames[:pair] + [{
                "scene_no": left["scene_no"],
                "title": left["title"],
                "copy": left["copy"] + right["copy"],
                "scene": (str(left.get("scene") or "").rstrip() + "\n" + str(right.get("scene") or "").lstrip()).strip(),
            }] + frames[pair + 2:]
        for index, frame in enumerate(frames, start=1):
            frame["scene_no"] = index
            frame["scene"] = str(frame.get("scene") or "").strip() or MULTI_REFERENCE_DEFAULT_SCENE
            frame["title"] = str(frame.get("title") or "").strip() or self._multi_reference_beat_title(frame.get("copy") or "", index)
        return frames

    def split_multi_reference_body_beats(self, body: str) -> list[dict]:
        """Cut the original body on sentence boundaries outside quotation marks.

        Joining the copies restores the body. A quoted sentence is never halved,
        so a line such as 「一家人」 stays on one frame.
        """
        text = str(body or "").replace("\r\n", "\n").replace("\r", "\n").strip()
        if not text:
            return []
        pieces = self._split_outside_quotes(text, "。！？!?；;\n")
        # 句号外的每个完整句子单独成张。短句不再按 72 字捆在一起，
        # 这样一篇大约 80 字、写成 5 拍的正文会落到 5 张图。
        # 短于 12 字的碎片并进上一张，避免标点单独成图。
        merged: list[str] = []
        for piece in pieces:
            if merged and len(piece.strip()) < 12:
                merged[-1] += piece
            else:
                merged.append(piece)
        if not merged or "".join(merged) != text:
            merged = [text]
        frames = [
            {
                "scene_no": index,
                "title": self._multi_reference_beat_title(copy, index),
                "copy": copy,
                "scene": MULTI_REFERENCE_DEFAULT_SCENE,
            }
            for index, copy in enumerate(merged, start=1)
        ]
        return self.limit_multi_reference_frames(frames)

    def parse_multi_reference_storyboard_blocks(self, text: str) -> list[dict]:
        """Read 场景画面N blocks that carry 【文案】 and 【场景】."""
        parsed = []
        for order, title, block in self.extract_storyboard_rule_scene_blocks(text):
            copy_match = re.search(r"【文案】\s*[:：]?\s*(.*?)(?=\n\s*【场景】|【场景】|\Z)", block, re.S)
            scene_match = re.search(r"【场景】\s*[:：]?\s*(.*)\Z", block, re.S)
            number_match = re.search(r"场景画面\s*(\d+)", block)
            try:
                number = int(number_match.group(1)) if number_match else order
            except (TypeError, ValueError):
                number = order
            parsed.append({
                "order": order,
                "number": number,
                "title": str(title or "").strip() or f"第{order}张",
                "copy": (copy_match.group(1) if copy_match else "").strip(),
                "scene": (scene_match.group(1) if scene_match else "").strip(),
            })
        return parsed

    def multi_reference_storyboard_rule_text(self, rule: dict | None, title: str, body: str, character_detail: str) -> str:
        template = ""
        if isinstance(rule, dict):
            template = str(rule.get("prompt_content", "") or rule.get("content", "") or "").strip()
        for token, value in {
            "${参考图}": "（参考图在生图阶段上传，这里不要写画风）",
            "${参考图说明}": "（参考图在生图阶段上传，这里不要写画风）",
            "${参考图名称}": "",
            "${画风}": self.STORYBOARD_STYLE_NOTICE,
            "${画风名称}": "",
            "${人物}": character_detail,
            "${人物方案}": character_detail,
            "${文章}": body,
            "${标题}": title,
            "${分镜数量}": "按叙事节点决定，不固定张数",
        }.items():
            template = template.replace(token, str(value or ""))
        return template.strip()

    def multi_reference_rule_frame_count(self, rule_text: str) -> int | None:
        """Read an explicit frame count such as “必须切成 5 张” from a storyboard rule."""
        match = re.search(r"(?:恰好|必须切成|必须输出)\s*(\d+)\s*张", str(rule_text or ""))
        if not match:
            return None
        count = int(match.group(1))
        if 1 <= count <= MULTI_REFERENCE_MAX_FRAMES:
            return count
        return None

    def multi_reference_supporting_cast_prompt(self, title: str, body: str, character_detail: str) -> str:
        """Ask for supporting appearances before any storyboard prompt is written."""
        character = "主角色身份只由本篇标题与正文确定，外貌在各分镜中保持同一套合理设定。"
        return (
            "你在切分镜之前，先为本篇锁定副角色形象。不要写分镜，不要改写正文，不要解释。\n"
            "本模式仅参考画风，不启用形象图或参考人物锁定。主角色与副角色的身份只能取本篇标题和正文；"
            "历史账号人设、参考图人物及其职业服装不属于本篇内容。副角色应与本篇主角色具有清楚的外貌区分。\n"
            "只根据正文判断除主角色以外还需要哪些人。不需要别人时，只输出一行：无副角色\n"
            f"最多 {MULTI_REFERENCE_MAX_SUPPORTING_CAST} 个。每个副角色单独一行，严格使用这个格式：\n"
            "副角色N：称呼｜年龄段｜发型｜服装｜和主角色的区分\n"
            "年龄、发型、服装颜色、配饰都要和主角色明显不同。副角色不能是主角色的缩小版，不能穿主角色的工作服。\n"
            "不要写画风、线条、配色方案、图片尺寸、边框或参考图。\n\n"
            f"【主角色】\n{character}\n\n"
            f"【标题】{title}\n"
            f"【正文】\n{body}\n"
        )

    def normalize_multi_reference_supporting_cast(self, text: str) -> str:
        """Keep a stable cast sheet. Extra people beyond the cap are dropped."""
        raw = str(text or "").strip()
        raw = re.sub(r"^```[a-zA-Z]*\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw).strip()
        if not raw:
            raise RuntimeError("副角色固定形象没有返回内容。")
        compact = re.sub(r"\s+", "", raw)
        people = []
        for line in raw.splitlines():
            line = line.strip().lstrip("-").strip()
            match = re.match(r"^(?:\d+[.、]\s*)?(?:副角色|配角)\s*(\d+)?\s*[:：]\s*(.+)$", line)
            if not match:
                continue
            body = re.sub(r"\s+", " ", match.group(2)).strip()
            name = re.split(r"[|｜]", body, maxsplit=1)[0].strip()
            if not body or body in {MULTI_REFERENCE_CAST_NONE, "无"} or name in {"主角色", "主角", MULTI_REFERENCE_CAST_NONE}:
                continue
            people.append(body)
        if not people:
            if MULTI_REFERENCE_CAST_NONE in compact:
                return MULTI_REFERENCE_CAST_NONE
            raise RuntimeError("副角色固定形象没有按“副角色N：”返回。")
        people = people[:MULTI_REFERENCE_MAX_SUPPORTING_CAST]
        return "\n".join(f"副角色{index}：{body}" for index, body in enumerate(people, start=1))

    def plan_multi_reference_supporting_cast(
        self, httpx, text_api: dict, title: str, body: str, character_detail: str,
        key_start: int, stop_event, attempts: int, label: str = "",
    ) -> str:
        """One cast sheet for the whole article. Storyboard prompts reuse it unchanged."""
        prompt = self.multi_reference_supporting_cast_prompt(title, body, character_detail)
        label = str(label or title or "多参考图生图").strip()
        last_error = ""
        total_attempts = max(1, int(attempts or 1))
        for attempt in range(1, total_attempts + 1):
            if self.account_generation_stop_requested or stop_event.is_set():
                raise RuntimeError("已请求停止。")
            context = {}
            try:
                self.account_generation_log(f"{label} 副角色形象固定：第 {attempt}/{total_attempts} 次，位于分镜之前。")
                answer = self.call_account_generation_text(
                    httpx, text_api, prompt, key_start, stop_event, conversation_context=context,
                )
                cast = self.normalize_multi_reference_supporting_cast(answer)
                self.account_generation_log(f"{label} 副角色已固定：{cast.replace(chr(10), '；')}")
                return cast
            except Exception as exc:
                if self.is_stop_error(str(exc)) or self.account_generation_stop_requested or stop_event.is_set():
                    raise
                last_error = str(exc)
                if attempt < total_attempts:
                    self.account_generation_log(f"{label} 副角色形象第 {attempt}/{total_attempts} 次失败，重试：{exc}")
                    continue
                raise RuntimeError(f"切分镜之前未能固定副角色形象：{last_error}") from exc
            finally:
                self.close_account_generation_text_context(context)
        raise RuntimeError(f"切分镜之前未能固定副角色形象：{last_error}")

    def multi_reference_cast_split_block(self, supporting_cast: str) -> str:
        """Constraint placed ahead of the storyboard request."""
        cast = str(supporting_cast or "").strip()
        if not cast:
            return ""
        if cast == MULTI_REFERENCE_CAST_NONE:
            return (
                "【副角色固定形象】\n"
                "切分镜之前已确定这一篇没有副角色。场景里不要安排主角色以外的人。\n\n"
            )
        return (
            "【副角色固定形象】\n"
            "下面的副角色在切分镜之前已经固定。写【场景】时只能使用这些称呼，并写动作和位置。\n"
            "不要在场景里重新设计年龄、发型、服装或配饰，也不要新增名单以外的人。\n"
            "副角色和主角色必须是不同的人。\n"
            f"{cast}\n\n"
        )

    def multi_reference_cast_image_block(self, supporting_cast: str) -> str:
        """The same cast sheet, repeated on every frame so concurrent images stay consistent."""
        cast = str(supporting_cast or "").strip()
        if not cast:
            return ""
        if cast == MULTI_REFERENCE_CAST_NONE:
            return (
                "【副角色固定形象】\n"
                "这一篇只有主角色。不要画第二个相似的人，不要把主角色的形象再画一份。\n"
            )
        return (
            "【副角色固定形象】\n"
            "这些副角色根据本篇正文确定，身份属于本篇故事。多参考图模式不启用形象图或参考人物锁定；"
            "任何参考图中的人脸、服装、人物照片和肖像均不能充当本篇角色。\n"
            "每一张都使用下面同一套年龄、发型、服装和区分特征，不能逐张改。\n"
            "主角色和副角色保持可区分的外貌，不画成同一个人的大小两份。"
            "只画本张分镜需要的角色；若人物仅出现在车贴、照片或手机画面中，不让其作为真人到场。\n"
            "如果场景里写的外貌和这里冲突，以这里的固定形象为准。\n"
            f"{cast}\n"
        )

    def multi_reference_storyboard_split_prompt(self, rule: dict | None, title: str, body: str, character_detail: str, supporting_cast: str = "") -> str:
        """Ask the storyboard rule where to cut. The copies themselves stay verbatim."""
        rule_text = self.multi_reference_storyboard_rule_text(rule, title, body, "")
        rule_block = f"【分镜规则】\n{rule_text}\n\n" if rule_text else ""
        cast_block = self.multi_reference_cast_split_block(supporting_cast)
        return (
            "你只负责把正文按叙事顺序切成多个分镜。不要把正文改写成文章，不要写留言，不要解释。\n"
            f"{rule_block}"
            "本模式的参考图只提供画风，不提供人物身份、场景事件或文字。分镜内容只依据下方的新标题与正文，"
            "不套用账号历史人设，不写按形象图锁定人物的要求。\n"
            "规则只用来判断在哪里切开、每一张画什么场景。"
            "正文必须整段用完：每一张【文案】都是正文里的连续原句，按场景画面序号首尾相接后必须正好等于整段正文。"
            "不允许只挑代表节点而丢掉其余句子，不允许概括，不允许改字，不允许把后文提前。"
            "引号里的话不能从中间断开。同一句对白不要拆开。"
            "按对话轮次、动作转折和句号外的完整句子切开。每个已经分开的完整句子各成一张，不要为了减少张数把下一句并进前一张。"
            "若分镜规则写明张数，必须按该张数切开，同时各张文案相接后仍等于全文。"
            f"没有写明张数时，张数由正文的叙事节点决定，最多 {MULTI_REFERENCE_MAX_FRAMES} 张；正文只有一句时可以只有 1 张。\n"
            "只输出分镜，每个分镜严格使用下面的格式：\n"
            "场景画面N：一句画面标题\n"
            "【文案】\n"
            "从正文按顺序原样抄出的连续片段\n"
            "【场景】\n"
            "这一张的地点、在场人物、动作、表情、道具和构图。不写画风、线条、配色、图片尺寸、参考图。"
            "图片尺寸在切分镜之前已经指定，每一张都相同，场景里不要再写。\n\n"
            "场景中涉及车贴、照片、海报、手机或屏幕时，写明其中人物的正文身份及需要显示的原句。"
            "对‘这句话’‘原标语’‘熟悉的符号’等指代，用正文中的对应人物或原文消歧，不能只写‘完整标语’等占位描述。"
            "区分原文、误译和网友评论，不要混用。正文未说明的图案或文字不自行添加。\n\n"
            f"{cast_block}"
            f"【标题】{title}\n"
            f"【正文】\n{body}\n"
        )

    def plan_multi_reference_storyboard_frames(
        self, httpx, text_api: dict, rule: dict | None, title: str, body: str,
        character_detail: str, key_start: int, stop_event, supporting_cast: str = "",
    ) -> list[dict]:
        """One text call cuts the body. The result is rejected unless it rebuilds the body."""
        prompt = self.multi_reference_storyboard_split_prompt(rule, title, body, character_detail, supporting_cast)
        context = {}
        try:
            answer = self.call_account_generation_text(
                httpx, text_api, prompt, key_start, stop_event, conversation_context=context,
            )
        finally:
            self.close_account_generation_text_context(context)
        blocks = self.parse_multi_reference_storyboard_blocks(answer)
        if not blocks:
            raise RuntimeError("分镜规则回答里没有场景画面。")
        aligned = self.align_multi_reference_storyboard_copies(body, blocks)
        if not aligned:
            raise RuntimeError(f"分镜规则回答的 {len(blocks)} 段文案没有按顺序还原整段正文。")
        return self.limit_multi_reference_frames(aligned)

    def multi_reference_canvas_spec(self, image_size: str) -> dict:
        """Lock one image size for the whole article before the storyboard is cut."""
        raw = str(image_size or "768x1024").lower().replace("×", "x").replace("*", "x")
        try:
            width, height = (int(part) for part in raw.split("x", 1))
        except (TypeError, ValueError):
            width, height = 768, 1024
        if width <= 0 or height <= 0:
            width, height = 768, 1024
        return {"size": f"{width}x{height}", "width": width, "height": height}

    def multi_reference_size_prompt(self, size: str) -> str:
        """The only shared picture constraint: every frame uses this size."""
        return f"【尺寸】\n本篇每一张图片都使用同一尺寸：{size}。不要改成别的宽高。\n\n"

    def build_multi_reference_frame_prompt(
        self, scene_no: int, total: int, scene_title: str, copy: str, scene: str,
        names: list[str], size: str, character: str = "", canvas: dict | None = None,
        supporting_cast: str = "", reference_roles: list[dict] | None = None,
        source_body: str = "",
    ) -> str:
        """Transfer visual style, while story content stays anchored to this story."""
        cleaned_names = self.normalize_multi_reference_names(names)
        listing = "\n".join(f"{index}. {name}" for index, name in enumerate(cleaned_names, start=1)) or "（按本次上传顺序）"
        roles = reference_roles or [{"name": name, "role": "background"} for name in cleaned_names]
        if roles:
            listing = "\n".join(
                f"第{index}张：{item['name']}；用途：仅参考画风，不提供人物、故事内容或文字"
                for index, item in enumerate(roles, start=1)
            )
        identity_rule = (
            "多参考图模式仅迁移画风，不启用形象图或参考人物锁定。无论历史配置给图片标注过什么用途，"
            "本次全部上传图都只作为绘制风格样本。主角色和副角色的身份、面孔、发型、服装及道具肖像均须依据"
            "本篇新标题、正文与本张分镜重新绘制，保持本篇人物设定连续；不能从参考图挑一张脸充当本篇人物。"
            "参考图若为人物设定表，也只提取绘画技法，不复制设定图的白底、多视角、人物或排版。\n"
        )
        context = str(source_body or "").strip()
        story_context = (
            "【本篇正文上下文：仅用于核对人物、指代和道具文字】\n"+context+"\n"
            "全文不是本张的展示文案，不把全文写进图片，也不提前画其他分镜。"
            "本张提到的原标语、车贴肖像、照片或屏幕内容，必须对应全文明确的人物身份和原句；"
            "不能用参考图人物或文字填补指代，更不能把误译当作原标语。\n\n"
            if context else ""
        )
        size_line = self.multi_reference_size_prompt(str((canvas or {}).get("size") or size))
        cast_line = self.multi_reference_cast_image_block(supporting_cast)
        return (
            f"【分镜序号】{int(scene_no)}/{int(total)}\n"
            f"【画面标题】{str(scene_title or '').strip() or f'第{scene_no}张'}\n"
            f"【本张文案】\n{str(copy or '').strip()}\n\n"
            f"【场景】\n{str(scene or '').strip() or MULTI_REFERENCE_DEFAULT_SCENE}\n\n"
            f"{story_context}"
            "【参考图】\n"
            "本次按下面的顺序实际上传原始参考图，按用途提取视觉特征；参考图不提供本篇剧情内容。\n"
            "参考图名称只用于对照上传顺序，不把名称中的人物、职业或故事词当作本文事实，也不在画面输出这些名称。\n"
            f"{listing}\n\n"
            f"{size_line}"
            "【多参考图生图】\n"
            "【内容与画风的边界】\n"
            "新图画什么，只由本篇正文、本张文案、场景和人物设定决定。背景与画风参考图是绘制方式的最高依据："
            "强参考其线条、油画或其他材质的笔触、色彩、光影、背景表现和文字容器风格，不套用默认漫画画风。"
            "版式仅参考文字留白、视觉密度和构图方法，具体人物、地点、道具及事件重新按新故事构图。"
            "参考图中出现的历史人物、示例人物、人物照片、原故事情节和物件均不属于新故事。\n"
            f"{identity_rule}"
            "【防止参考内容混入】\n"
            "画风参考图里的脸和人物，禁止以任何形式带入：主角、配角、路人、车贴肖像、海报、照片、手机屏幕或其他画中画都不可以。"
            "画风图里的标题、口号、字幕、标志、页码和原场景文字也禁止照搬到新画面及其任何道具中。"
            "道具中的肖像和标语同样属于故事内容，必须按正文指定身份和原句重绘，不能裁取或模仿画风图里的人物和文字。"
            "即使两篇都属于同一赛道，也不得把参考图内容当成本文素材。每张参考图只贡献其用途允许的视觉特征，不要求移入各图里的具体内容。\n"
            f"{cast_line}"
            f"这是连续故事的第 {int(scene_no)} 张，共 {int(total)} 张。"
            "只画本张文案和本张场景，不要画成宫格，不要把其他分镜画进这一张。"
            "有引号的句子放进对应角色的气泡，没有引号的句子也写进画面。本张文案逐字保留，不要概括或漏句。"
            "同篇人物按本篇分镜的人物设定持续一致，禁止用任何参考图人物替代或补充故事角色。"
            "交付前核对所有画中人物与文字，包括车贴、照片和屏幕：均来自本篇故事；仅作画风的参考图内容不得出现。"
        )

    def generate_one_multi_reference_frame(
        self, httpx, image_api: dict, scene: dict, image_size: str, max_file_size_mb: float,
        key_start: int, stop_event, reference_paths: list[str], post_process: dict | None, label: str,
    ) -> None:
        """Generate one numbered frame. It uploads the same references and no previous picture."""
        path = Path(str(scene.get("image_path") or ""))
        scene_no = int(scene.get("scene_no") or 0)
        total = int(scene.get("scene_total") or scene_no or 1)
        if path.is_file() and path.stat().st_size > 0:
            return
        paths = [str(item).strip() for item in reference_paths if str(item).strip()]
        if not paths:
            raise RuntimeError("多参考图生图没有可上传的参考图。")
        self.account_generation_log(f"{label} 图片 {scene_no}/{total}：开始调用图片接口，上传 {len(paths)} 张参考图。")
        try:
            self.call_multi_reference_image_generation(
                httpx,
                image_api,
                str(scene.get("image_prompt") or ""),
                str(path),
                image_size,
                max_file_size_mb,
                key_start,
                stop_event,
                log_func=self.account_generation_log,
                reference_image_path=paths[0],
                post_process=post_process,
                extra_reference_paths=paths[1:],
            )
        except Exception as exc:
            if not self.is_stop_error(str(exc)) and path.is_file():
                try:
                    path.unlink()
                except OSError:
                    pass
            raise
        self.account_generation_log(f"{label} 图片 {scene_no}/{total}：生成成功，文件 {path.name}。")

    def generate_multi_reference_frames_concurrent(
        self, httpx, image_api: dict, scenes: list[dict], image_size: str, max_file_size_mb: float,
        stop_event, reference_paths: list[str], post_process: dict | None, label: str, max_workers: int,
    ) -> None:
        """Run independent frames together. File names already carry the story order."""
        pending = []
        for scene in scenes:
            path = Path(str(scene.get("image_path") or ""))
            if path.is_file() and path.stat().st_size > 0:
                self.account_generation_log(f"{label} 图片 {scene.get('scene_no')}/{len(scenes)}：已生成，断点续跑跳过。")
                continue
            pending.append(scene)
        if not pending:
            return
        worker_count = max(1, min(len(pending), int(max_workers or 1), 4))
        self.account_generation_log(
            f"{label} 多参考图生图并发 {worker_count} 张，本次 {len(pending)}/{len(scenes)} 张。每张上传同一套参考图，不附上一张成图。"
        )
        errors = []
        keys = list(image_api.get("keys") or [])
        pool = concurrent.futures.ThreadPoolExecutor(max_workers=worker_count)
        try:
            futures = {}
            for scene in pending:
                key_start = self.next_image_api_key_start(len(keys)) if keys else 0
                futures[pool.submit(
                    self.generate_one_multi_reference_frame,
                    httpx, image_api, scene, image_size, max_file_size_mb, key_start,
                    stop_event, reference_paths, post_process, label,
                )] = scene
            for future in concurrent.futures.as_completed(futures):
                scene = futures[future]
                try:
                    future.result()
                except Exception as exc:
                    errors.append((int(scene.get("scene_no") or 0), exc))
        finally:
            pool.shutdown(wait=True, cancel_futures=False)
        if not errors:
            return
        errors.sort(key=lambda item: item[0])
        for _scene_no, exc in errors:
            if self.is_stop_error(str(exc)):
                raise exc
        raise errors[0][1]

    def write_multi_reference_publish_text(self, output_dir: Path, final_article: str) -> None:
        """多参考图生图只落一份发布正文，文件名固定为「文章.txt」，内容不改写。"""
        (Path(output_dir) / MULTI_REFERENCE_ARTICLE_FILENAME).write_text(str(final_article or ""), encoding="utf-8")

    def execute_multi_reference_account_title(self, httpx, text_api: dict, image_api: dict, account: dict, title_record: dict, config: dict, article_template: dict | None, storyboard_rule: dict, binding: dict, stop_event) -> dict:
        """多参考图生图：正文切成有序号的分镜后并发生图。不改写正文，作品目录写入「文章.txt」。不接力上一张。"""
        del article_template  # 这个模式不调用文章提示词。
        started_at = time.time()
        work_id = str(title_record.get("_work_uuid", "") or "").strip() or self.record_uuid()
        title = str(title_record.get("title", "")).strip()
        title_log_label = str(title_record.get("log_label", "") or "").strip() or (title[:12] + "…")
        account_label = str(account.get("name", account.get("account_id", "账号"))).strip()
        binding_name = str(binding.get("name", "")).strip()
        binding_image_path = str(binding.get("image_path", "") or "").strip()
        reference_paths = [str(path).strip() for path in (binding.get("image_paths") or []) if str(path).strip()]
        reference_names = self.normalize_multi_reference_names(binding.get("names"))
        configured_image_size = str(config.get("image_size", "768x1024") or "768x1024")
        binding_image_size = self.reference_image_request_size(binding, configured_image_size)
        character_detail = self.account_generation_character_detail(account)
        remove_ai_enabled = self.account_generation_remove_ai_enabled(account)
        refine_enabled = self.account_refine_enabled(account)
        article_tag_text = str(account.get("article_tag", "") or "").strip()
        output_dir, _article_filename = self.account_generation_work_paths(config["output_root"], account, title)
        source_body = self.account_generation_source_body(title_record).strip()
        scenes: list[dict] = []
        work = {
            "uuid": work_id, "account_id": account.get("account_id", ""), "account_name": account.get("name", ""),
            "title": title, "log_label": title_log_label, "category": title_record.get("category", ""),
            "status": "生成中", "article": "", "comment": "", "generation_mode": GENERATION_MODE_MULTI_REFERENCE,
            "style_name": binding_name, "reference_name": binding_name, "reference_image_path": binding_image_path, "reference_image_paths": reference_paths, "reference_roles": binding.get("reference_roles", []),
            "image_size": binding_image_size, "grid": GRID_LAYOUT_SINGLE, "split_images": False,
            "refine_images": refine_enabled, "source_body": source_body, "character_feature": character_detail,
            "remove_ai": remove_ai_enabled, "output_dir": str(output_dir), "scenes": [],
            "updated_at": self.record_updated_at(),
        }
        work["retry_count"] = int(title_record.get("_retry_count", 0) or 0)
        attempts = max(1, int(config.get("group_retry_count", 2) or 0) + 1)
        text_key_start = self.next_text_api_key_start(len(text_api.get("keys") or []))
        try:
            if not source_body:
                raise RuntimeError("多参考图生图的正文为空，无法切分分镜。")
            if not reference_paths:
                raise RuntimeError(f"公众号「{account_label}」的多参考图生图没有可上传的参考图。")
            canvas = self.multi_reference_canvas_spec(binding_image_size)
            binding_image_size = canvas["size"]
            work["image_size"] = binding_image_size
            work["multi_reference_canvas"] = {"size": canvas["size"]}
            self.account_generation_log(
                f"{title_log_label} 分镜前已指定统一尺寸：{canvas['size']}。"
            )
            supporting_cast = self.plan_multi_reference_supporting_cast(
                httpx, text_api, title, source_body, character_detail, text_key_start, stop_event, attempts, title_log_label,
            )
            work["multi_reference_supporting_cast"] = supporting_cast
            if self.account_grid_layout(account):
                self.account_generation_log(f"{title_log_label} 多参考图生图按分镜逐张出图，不合成宫格。")
            rule_text = self.multi_reference_storyboard_rule_text(storyboard_rule, title, source_body, character_detail)
            frames = None
            if not rule_text:
                frames = self.split_multi_reference_body_beats(source_body)
                self.account_generation_log(f"{title_log_label} 未配置分镜规则，正文按原文顺序切成 {len(frames)} 个分镜。")
            else:
                split_error = None
                for attempt in range(1, attempts + 1):
                    if self.account_generation_stop_requested or stop_event.is_set():
                        raise RuntimeError("已请求停止。")
                    try:
                        self.account_generation_log(f"{title_log_label} 分镜切分开始：第 {attempt}/{attempts} 次，不改写正文。")
                        frames = self.plan_multi_reference_storyboard_frames(
                            httpx, text_api, storyboard_rule, title, source_body, character_detail, text_key_start, stop_event,
                            supporting_cast,
                        )
                        expected_frames = self.multi_reference_rule_frame_count(rule_text)
                        if expected_frames and len(frames) != expected_frames:
                            raise RuntimeError(f"分镜规则要求 {expected_frames} 张，实际还原出 {len(frames)} 张。")
                        self.account_generation_log(f"{title_log_label} 分镜规则已按顺序切出 {len(frames)} 张，文案可还原正文。")
                        break
                    except Exception as exc:
                        if self.is_stop_error(str(exc)) or self.account_generation_stop_requested or stop_event.is_set():
                            raise
                        split_error = exc
                        if attempt < attempts:
                            self.account_generation_log(f"{title_log_label} 分镜切分第 {attempt}/{attempts} 次失败，重试：{exc}")
                            continue
                        frames = self.split_multi_reference_body_beats(source_body)
                        self.account_generation_log(
                            f"{title_log_label} 分镜规则未能按顺序还原正文（{split_error}），已按原文顺序切成 {len(frames)} 个分镜。"
                        )
                        break
            if not frames:
                raise RuntimeError("多参考图生图没有切出分镜。")
            order_text = "、".join(f"{item['scene_no']}.{item['title']}" for item in frames)
            self.account_generation_log(f"{title_log_label} 分镜序号：{order_text}。")
            comment = ""
            save_comment = self.account_save_comment_enabled(account)
            if save_comment:
                for attempt in range(1, attempts + 1):
                    if self.account_generation_stop_requested or stop_event.is_set():
                        raise RuntimeError("已请求停止。")
                    text_context = {}
                    try:
                        self.account_generation_log(f"{title_log_label} 留言生成中…")
                        comment_category = str(title_record.get("category", "") or account.get("title_category", "")).strip()
                        comment_template = self.account_generation_comment_template(comment_category)
                        raw_comment = self.call_account_generation_text(
                            httpx, text_api,
                            self.account_generation_comment_prompt(account, title, source_body, comment_template),
                            text_key_start, stop_event, conversation_context=text_context,
                        )
                        comment = self.clean_account_generation_comment(raw_comment)
                        if not comment:
                            raise RuntimeError("留言互动语接口未返回有效内容。")
                        self.account_generation_log(f"{title_log_label} 留言完成：{comment}")
                        break
                    except Exception as exc:
                        if attempt < attempts and not (self.is_stop_error(str(exc)) or self.account_generation_stop_requested or stop_event.is_set()):
                            self.account_generation_log(f"{title_log_label} 留言第 {attempt}/{attempts} 次失败，重试：{exc}")
                            continue
                        raise
                    finally:
                        self.close_account_generation_text_context(text_context)
            total = len(frames)
            scenes = []
            for frame in frames:
                image_prompt = self.build_multi_reference_frame_prompt(
                    frame["scene_no"], total, frame["title"], frame["copy"], frame["scene"],
                    reference_names, binding_image_size, character_detail, canvas, supporting_cast, binding.get("reference_roles"), source_body=source_body,
                )
                scenes.append({
                    "scene_no": frame["scene_no"],
                    "title": frame["title"],
                    "prompt": frame["scene"],
                    "copy": frame["copy"],
                    "image_prompt": image_prompt,
                    "image_path": str(output_dir / f"{frame['scene_no']}.jpg"),
                    "scene_total": total,
                    "status": "待生成",
                })
            if "".join(scene["copy"] for scene in scenes) != source_body:
                raise RuntimeError("多参考图生图分镜文案与正文不一致，已停止生图。")
            self.clear_account_generation_outputs(output_dir)
            output_dir.mkdir(parents=True, exist_ok=True)
            final_article = source_body
            if save_comment and comment:
                final_article += "\n\n" + comment
            if article_tag_text:
                final_article += "\n\n" + article_tag_text
            self.write_multi_reference_publish_text(output_dir, final_article)
            work.update({
                "article": final_article, "article_source": source_body, "comment": comment,
                "scenes": scenes, "updated_at": self.record_updated_at(),
            })
            self.persist_generated_work(work)
            max_file_size_mb = float(config.get("max_file_size_mb", 1) or 1)
            frame_workers = max(1, min(int(config.get("max_workers", 2) or 2), 4))
            post_process = {"size": binding_image_size, "margin_px": 0}
            for attempt in range(1, attempts + 1):
                if self.account_generation_stop_requested or stop_event.is_set():
                    raise RuntimeError("已请求停止。")
                self.account_generation_log(
                    f"{title_log_label} 生图阶段开始：第 {attempt}/{attempts} 次，共 {len(scenes)} 张，尺寸 {canvas['size']}，参考图 {len(reference_paths)} 张。"
                )
                try:
                    self.generate_multi_reference_frames_concurrent(
                        httpx, image_api, scenes, binding_image_size, max_file_size_mb, stop_event,
                        reference_paths, post_process, title_log_label, frame_workers,
                    )
                    missing = [scene["scene_no"] for scene in scenes if not Path(scene["image_path"]).is_file()]
                    if missing:
                        raise RuntimeError(f"多参考图生图缺少序号图片：{'、'.join(str(number) for number in missing)}。")
                    if remove_ai_enabled:
                        self.account_generation_log(f"{title_log_label} 启用去AI，开始处理 {len(scenes)} 张图片。")
                        completed, clarity_failed, clarity_errors = self.process_remove_ai_folder(output_dir, output_dir, overwrite=True)
                        if clarity_failed or completed != len(scenes):
                            detail = "；".join(clarity_errors[:3])
                            raise RuntimeError(f"去AI处理失败：成功 {completed}/{len(scenes)} 张。{detail}")
                    if refine_enabled:
                        self.account_generation_log(f"{title_log_label} 按“图片精修”工作区的默认配置处理成图。")
                        refined, failed, refine_errors = self.refine_images_in_place(output_dir, dict(self.image_refine_defaults), skip_names=frozenset())
                        work["refine_result"] = {"success": refined, "failed": failed, "errors": refine_errors[:5]}
                        self.account_generation_log(
                            f"{title_log_label} 精修完成：成功 {refined} 张，失败 {failed} 张。"
                            + (f" 失败：{'；'.join(refine_errors[:3])}" if refine_errors else "")
                        )
                    for scene in scenes:
                        scene["status"] = "成功"
                    work.update({"status": "成功", "scenes": scenes, "updated_at": self.record_updated_at(), "elapsed_seconds": time.time() - started_at})
                    self.persist_generated_work(work)
                    self.account_generation_log(f"标题任务完成：{title_log_label}（{account_label}）成功，多参考图生图 {len(scenes)} 张已按序号写入，正文已写入「{MULTI_REFERENCE_ARTICLE_FILENAME}」。")
                    return work
                except Exception as exc:
                    stop_now = self.is_stop_error(str(exc)) or self.account_generation_stop_requested or stop_event.is_set()
                    if attempt < attempts and not stop_now:
                        self.account_generation_log(f"{title_log_label} 生图第 {attempt}/{attempts} 次失败，保留已成功图片，断点续跑重试：{exc}")
                        continue
                    raise
        except Exception as exc:
            stopped = self.is_stop_error(str(exc)) or self.account_generation_stop_requested or stop_event.is_set()
            work.update({
                "status": "停止" if stopped else "失败", "error": str(exc),
                "scenes": [{**scene, "status": scene.get("status") if scene.get("status") == "成功" else "失败"} for scene in scenes],
                "updated_at": self.record_updated_at(), "elapsed_seconds": time.time() - started_at,
            })
            self.persist_generated_work(work)
            self.account_generation_log(f"标题任务结束：{title_log_label}（{account_label}）{work['status']}，原因：{exc}")
            return work

    def call_multi_reference_image_generation(
        self,
        httpx,
        api_config: dict,
        prompt: str,
        save_path: str,
        image_size: str,
        max_file_size_mb: float,
        key_start_index: int = 0,
        stop_event=None,
        log_func=None,
        client=None,
        conversation_context: dict | None = None,
        fixed_key: bool = False,
        reference_image_path: str | None = None,
        post_process: dict | None = None,
        continuity_image_path: str | None = None,
        extra_reference_paths: list | None = None,
    ):
        payload = {"model": api_config["model"], "prompt": prompt, "size": image_size}
        # With a reference image the request becomes multipart against the
        # edits endpoint; plain JSON generations stay untouched otherwise.
        reference_path = Path(reference_image_path) if str(reference_image_path or "").strip() else None
        if reference_path is None:
            raise RuntimeError("多参考图生图必须实际上传参考图，不能降级为纯文字生图。")
        if reference_path is not None and not reference_path.is_file():
            raise RuntimeError(f"参考图文件不存在：{reference_path}")
        continuity_path = Path(continuity_image_path) if str(continuity_image_path or "").strip() else None
        if continuity_path is not None:
            raise RuntimeError("多参考图生图只使用账号选定的原始参考图，不接入上一张成图。")
        if continuity_path is not None and not continuity_path.is_file():
            raise RuntimeError(f"上一张成图不存在，无法承接：{continuity_path}")
        send_continuity = continuity_path is not None and reference_path is not None
        extra_paths = []
        for raw_path in extra_reference_paths or []:
            extra_path = Path(str(raw_path))
            if not extra_path.is_file():
                raise RuntimeError(f"参考图文件不存在：{extra_path}")
            extra_paths.append(extra_path)
        endpoint = api_config["endpoint"]
        if reference_path is not None:
            endpoint = str(api_config.get("edit_endpoint", "") or "").strip() or self.derive_image_edit_endpoint(api_config["endpoint"], api_config.get("base_url", ""))
        # Some compatible gateways expose an optional conversation/session field.
        # Only forward explicitly configured fields so ordinary /images/generations
        # endpoints continue to receive their standard payload.
        if conversation_context and api_config.get("use_response_context", False):
            for field in ("conversation_id", "session_id", "previous_response_id"):
                value = conversation_context.get(field)
                if value:
                    payload[field] = value
        last_error = ""
        ordered_keys = (
            [api_config["keys"][key_start_index % len(api_config["keys"])] ]
            if fixed_key and api_config.get("keys")
            else self.rotated_api_keys(api_config["keys"], key_start_index)
        )
        for key_offset, key in enumerate(ordered_keys):
            key_index = ((key_start_index + key_offset) % len(api_config["keys"])) + 1
            if self.image_batch_stop_requested or (stop_event is not None and stop_event.is_set()):
                raise RuntimeError("已请求停止。")
            headers = {
                "Authorization": f"Bearer {key}",
                "Accept": "application/json",
                "User-Agent": "Mozilla/5.0",
            }
            if reference_path is None:
                headers["Content-Type"] = "application/json"
            for attempt in range(1, 4):
                try:
                    if attempt > 1:
                        (log_func or self.image_batch_log)(
                            f"图片请求重试：Key {key_index}/{len(api_config['keys'])}，第 {attempt}/3 次。"
                        )
                    request_client = client or httpx.Client(
                        timeout=httpx.Timeout(float(api_config.get("timeout_seconds", 180) or 180), connect=30.0),
                        verify=False,
                        follow_redirects=True,
                    )
                    owns_client = client is None
                    if owns_client:
                        self.register_active_http_client(request_client, self.image_batch_active_clients, self.image_batch_active_clients_lock)
                    try:
                        if reference_path is not None:
                            import mimetypes
                            upload_paths = [reference_path, *extra_paths]
                            if send_continuity and continuity_path is not None:
                                upload_paths.append(continuity_path)
                            handles = []
                            try:
                                files = []
                                for path in upload_paths:
                                    mime_type = mimetypes.guess_type(path.name)[0] or "image/png"
                                    handle = path.open("rb")
                                    handles.append(handle)
                                    files.append((path.name, handle, mime_type))
                                # One image keeps the original single ``image`` field.
                                # A second file is the previous frame and is sent
                                # under the same field name, after the style reference.
                                file_payload = {"image": files[0]} if len(files) == 1 else [("image", item) for item in files]
                                response = request_client.post(
                                    endpoint,
                                    headers=headers,
                                    data={field: str(value) for field, value in payload.items()},
                                    files=file_payload,
                                )
                            finally:
                                for handle in handles:
                                    try:
                                        handle.close()
                                    except Exception:
                                        pass
                        else:
                            response = request_client.post(endpoint, headers=headers, json=payload)
                    finally:
                        if owns_client:
                            self.unregister_active_http_client(request_client, self.image_batch_active_clients, self.image_batch_active_clients_lock)
                            try:
                                request_client.close()
                            except Exception:
                                pass
                    if self.image_batch_stop_requested or (stop_event is not None and stop_event.is_set()):
                        raise RuntimeError("已请求停止。")
                    text = response.text
                    if response.status_code != 200:
                        last_error = f"HTTP {response.status_code}: {text[:500]}"
                        optional_context = {"conversation_id", "session_id", "previous_response_id"}
                        if response.status_code in {400, 404, 422} and conversation_context and not conversation_context.get("_response_context_disabled") and any(field in payload for field in optional_context):
                            # Compatibility fallback for ordinary image gateways
                            # that reject optional conversation fields.
                            for field in optional_context:
                                payload.pop(field, None)
                            conversation_context["_response_context_disabled"] = True
                            last_error = "图片网关不支持会话字段，已降级为固定客户端串行模式"
                            continue
                        if response.status_code == 400 and send_continuity:
                            send_continuity = False
                            last_error = "图片网关未接受上一张承接图，本张改为只上传原始参考图。"
                            (log_func or self.image_batch_log)(last_error)
                            continue
                        if "text_conversation_not_supported" in text.lower() or "cannot process text conversation" in text.lower():
                            raise RuntimeError(
                                "图片接口/模型配置错误：当前请求被当作文本对话处理。"
                                + ("请确认参考图接口为 /images/edits（可用 image_edit_endpoint 指定）、模型为 gpt-image-2，" if reference_path is not None else "请确认图片接口为 /images/generations、模型为 gpt-image-2，")
                                + "并关闭不兼容的会话字段。"
                            )
                        if self.is_image_key_error(text, response.status_code):
                            break
                        if response.status_code in {429, 500, 502, 503, 504} and attempt < 3:
                            if self.wait_with_stop(8 * attempt, stop_event):
                                raise RuntimeError("已请求停止。")
                            continue
                        raise RuntimeError(last_error)
                    data = response.json()
                    image_type, image_value = self.extract_image_generation_payload(data)
                    if not image_type or not image_value:
                        last_error = "接口返回中未找到 url 或 b64_json。"
                        if attempt < 3:
                            if self.wait_with_stop(5 * attempt, stop_event):
                                raise RuntimeError("已请求停止。")
                            continue
                        raise RuntimeError(last_error)
                    self.save_image_payload(image_type, image_value, httpx=httpx, save_path=save_path, stop_event=stop_event, client=None if owns_client else request_client)
                    post_process_info = None
                    if post_process:
                        try:
                            post_process_info = self.normalize_generated_image(save_path, post_process)
                            (log_func or self.image_batch_log)(f"图片后处理：{post_process_info['message']}。")
                        except Exception as exc:  # noqa: BLE001  后处理失败不能吞掉已成功的生成
                            (log_func or self.image_batch_log)(f"图片后处理失败（保留原图）：{exc}")
                    self.compress_image_under_size(save_path, max_file_size_mb)
                    if post_process_info and isinstance(data, dict):
                        data["_local_post_process"] = post_process_info
                    return data
                except Exception as exc:
                    last_error = str(exc)
                    if "图片接口/模型配置错误" in last_error:
                        # This is a deterministic endpoint/model mismatch;
                        # repeating the same request cannot fix it.
                        break
                    if attempt < 3 and not self.is_image_key_error(last_error):
                        if self.wait_with_stop(5 * attempt, stop_event):
                            raise RuntimeError("已请求停止。")
                        continue
                    break
            (log_func or self.image_batch_log)(f"图片 Key {key_index}/{len(api_config['keys'])} 失败：{last_error}")
        raise RuntimeError(f"所有图片 API Key 均失败：{last_error}")
