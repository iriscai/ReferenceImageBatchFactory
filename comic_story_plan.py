"""Local, auditable speech/narration plans for reference-image comic grids.

Uncertain attribution stays in narration and is flagged instead of being guessed.
All text spans retain their source offsets so the original can be reconstructed.
"""

import re

from comic_copy_layout import split_comic_copy


PLAN_VERSION = "comic-panel-containers-v3"
_PAIRS = {"“": "”", "‘": "’", "「": "」", "『": "』", '"': '"', "'": "'"}
_ROLE_ALIASES = {
    "老婆": "妻子", "媳妇": "妻子", "妻子": "妻子", "老公": "丈夫", "丈夫": "丈夫",
    "妈妈": "妈妈", "爸爸": "爸爸", "婆婆": "婆婆", "公公": "公公", "岳母": "岳母", "岳父": "岳父",
    "女儿": "女儿", "儿子": "儿子", "弟弟": "弟弟", "妹妹": "妹妹", "哥哥": "哥哥", "姐姐": "姐姐",
    "嫂子": "嫂子", "姐夫": "姐夫", "小舅子": "小舅子", "闺蜜": "闺蜜", "男友": "男友", "女友": "女友",
    "经理": "经理", "老板": "老板", "同事": "同事", "领导": "领导", "医生": "医生", "老师": "老师",
    "顾客": "顾客", "店员": "店员", "司机": "司机", "乘客": "乘客", "乘务员": "乘务员", "警察": "警察",
}
_FEMALE = {"妻子", "妈妈", "婆婆", "岳母", "女儿", "妹妹", "姐姐", "嫂子", "闺蜜", "女友"}
_MALE = {"丈夫", "爸爸", "公公", "岳父", "儿子", "弟弟", "哥哥", "姐夫", "小舅子", "男友"}
_ROLE_RE = re.compile("|".join(sorted(_ROLE_ALIASES, key=len, reverse=True)))
_SPEECH = r"(?:追问|反问|问道|说道|骂道|答道|回答|解释|喊道|叫道|接话|补充|嘀咕|心想|心里想|腹诽|问|说|喊|叫|道)"
_PLACE_RE = re.compile(r"客厅|家里|家中|厨房|卧室|楼道|办公室|公司|教室|学校|医院|银行|饭店|餐厅|商场|超市|公园|高铁|列车|车厢|地铁|公交车|车站|机场")


def _quote_spans(text):
    stack = []
    start = None
    spans = []
    for index, char in enumerate(text):
        if char == "'" and index and index + 1 < len(text) and text[index - 1].isalnum() and text[index + 1].isalnum():
            continue
        if stack and char == stack[-1]:
            stack.pop()
            if not stack:
                spans.append((start, index + 1))
        elif char in _PAIRS:
            if not stack:
                start = index
            stack.append(_PAIRS[char])
    return spans


def _narrative_text(text):
    chars = list(text)
    for start, end in _quote_spans(text):
        chars[start:end] = " " * (end - start)
    return "".join(chars)


class _Roles:
    def __init__(self, body):
        narration = _narrative_text(body)
        self.roles = {}
        for match in _ROLE_RE.finditer(narration):
            self.add(_ROLE_ALIASES[match.group()])
        self.narrator = "我"
        # Treat the common spouse relation as a local inference, not a new
        # line of dialogue or a rewrite of the source.
        own_wife = re.search(r"(?:^|[，,。！？!?；;\n])(?:我(?:的|家)?)?(?:老婆|妻子|媳妇)", narration)
        own_husband = re.search(r"(?:^|[，,。！？!?；;\n])(?:我(?:的|家)?)?(?:老公|丈夫)", narration)
        if own_wife and "丈夫" not in self.roles:
            self.narrator = "丈夫"
        elif own_husband and "妻子" not in self.roles:
            self.narrator = "妻子"
        if re.search(r"我(?!们)", narration):
            self.add(self.narrator)

    def add(self, name):
        if name and name not in self.roles:
            gender = "女性" if name in _FEMALE else "男性" if name in _MALE else "依原文，未明示时不推断职业或身份"
            self.roles[name] = {"name": name, "gender": gender}
        return name

    def resolve(self, name, before):
        if name == "我":
            return self.add(self.narrator)
        if name == "嫂子" and "妻子" in self.roles:
            return "妻子"
        if name in ("她", "他"):
            wanted = _FEMALE if name == "她" else _MALE
            mentions = []
            narration = _narrative_text(before)
            for match in re.finditer(_ROLE_RE.pattern + r"|我(?!们)", narration):
                raw = match.group()
                resolved = self.narrator if raw == "我" else _ROLE_ALIASES[raw]
                if resolved in wanted:
                    mentions.append(resolved)
            candidates = list(dict.fromkeys(mentions))
            if len(candidates) == 1:
                return self.add(candidates[0])
            # Multiple possible antecedents are not resolved by gender alone.
            return ""
        return self.add(_ROLE_ALIASES.get(name, name))


def _speaker(before, roles):
    previous_quotes = _quote_spans(before)
    # Speaker leads after an earlier quote must not absorb that quote's closing
    # punctuation or inherit its speaker, including when both share one panel.
    tail = before[previous_quotes[-1][1]:] if previous_quotes else before
    trimmed = tail.rstrip()
    colon = trimmed.endswith(("：", ":"))
    lead = trimmed.rstrip("：: \t\r\n")
    clause = re.split(r"[，,。！？!?；;\n]", lead)[-1].strip()
    verb = re.search(_SPEECH + r"\s*$", clause)
    thought = bool(re.search(r"心想|心里|腹诽|内心|默默", clause))
    if not colon and not verb:
        return "", thought, False
    # A known role at the start also handles action leads: 弟弟站起来：…
    known_names = sorted(set(_ROLE_ALIASES) | set(roles.roles) | {"我", "她", "他"}, key=len, reverse=True)
    role = re.match(r"(?:" + "|".join(re.escape(name) for name in known_names) + r")(?!们)", clause)
    if role and not clause[len(role.group()):].startswith("的"):
        return roles.resolve(role.group(), before), thought, True
    candidate = clause[:verb.start()].strip() if verb else clause
    candidate = re.sub(r"[（(].*?[）)]", "", candidate)
    candidate = re.split(r"在|站|坐|转|走|抬|低|看|笑|哭|慢悠悠|轻声|小声|大声|突然|马上|缓缓|接着", candidate)[0].strip()
    if candidate in {"说明", "结果", "标题", "答案", "内容", "提示", "重点", "结论", "备注", "示例", "题目"}:
        return "", thought, False
    if re.fullmatch(r"[\u4e00-\u9fffA-Za-z0-9·]{1,8}", candidate):
        return roles.resolve(candidate, before), thought, True
    return "", thought, True


def _setting(body):
    evidence = list(dict.fromkeys(_PLACE_RE.findall(_narrative_text(body))))
    if evidence:
        return {"basis": "原文明示", "evidence": evidence, "description": "按原文出现顺序使用这些场所：" + "、".join(evidence) + "。只有原文发生转场时才转场。"}
    if "下楼" in body and re.search(r"老婆|妻子|老公|丈夫|嫂子", body):
        return {"basis": "根据亲属日常互动与下楼动作推定，可人工调整", "evidence": ["亲属日常互动", "下楼"], "description": "同一处普通住宅室内，离开方向连接门口、楼道和楼梯；末格只表现起身准备离开，不提前画成已经买到东西。"}
    return {"basis": "原文未明示", "evidence": [], "description": "使用简洁、中性的日常环境，各格空间连续；不要从参考图补入故事没有交代的特殊场所、职业或事件。"}


def _unquoted_dialogues(segment, body, roles):
    """Recognize explicit 爸爸说：… leads without reclassifying headings."""
    if segment["kind"] != "narration":
        return [segment]
    source = segment["source"]
    expanded = []
    cursor = 0
    for colon in re.finditer(r"[：:]", source):
        start = colon.end()
        if start < cursor or not source[start:].strip() or source[start:].lstrip()[:1] in _PAIRS:
            continue
        absolute = segment["start"] + start
        speaker, thought, _ = _speaker(body[:absolute], roles)
        if not speaker:
            continue
        stop = re.search(r"[。！？!?；;\n]", source[start:])
        end = start + stop.end() if stop else len(source)
        if start > cursor:
            text = source[cursor:start]
            expanded.append({"kind": "narration", "text": text, "source": text, "start": segment["start"] + cursor, "end": absolute})
        text = source[start:end]
        expanded.append({"kind": "thought" if thought else "dialogue", "speaker": speaker, "text": text, "source": text, "start": absolute, "end": segment["start"] + end})
        cursor = end
    if cursor < len(source):
        text = source[cursor:]
        expanded.append({"kind": "narration", "text": text, "source": text, "start": segment["start"] + cursor, "end": segment["end"]})
    return expanded


def build_comic_plan(body: str, count: int) -> dict:
    text = str(body or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    slices = split_comic_copy(text, count)
    roles = _Roles(text)
    panels = []
    warnings = []
    offset = 0
    last_speaker = None
    for number, piece in enumerate(slices, 1):
        segments = []
        cursor = 0
        for start, end in _quote_spans(piece):
            speaker, thought, speech_lead = _speaker(text[:offset + start], roles)
            if not speaker:
                if speech_lead:
                    warnings.append({"code": "unresolved_speaker", "panel": number, "message": "引语的说话人未能唯一确认，保留在旁白中，请人工复核。"})
                continue
            if start > cursor:
                segments.append({"kind": "narration", "text": piece[cursor:start], "source": piece[cursor:start], "start": offset + cursor, "end": offset + start})
            segments.append({"kind": "thought" if thought else "dialogue", "speaker": speaker, "text": piece[start + 1:end - 1], "source": piece[start:end], "start": offset + start, "end": offset + end})
            cursor = end
            for claim in re.finditer(r"你(?:刚才|刚刚|前面|之前)(?:还|明明)?说(?:过|的)?[：:]?([^，,。！？?!：:“”]{2,16})", piece[start + 1:end - 1]):
                if claim.group(1) not in text[:offset + start]:
                    warnings.append({"code": "unverified_reported_claim", "panel": number, "message": "台词引用的前文说法“" + claim.group(1) + "”未能在此前原文中核对，请复核；程序保留原文。"})
        if cursor < len(piece):
            segments.append({"kind": "narration", "text": piece[cursor:], "source": piece[cursor:], "start": offset + cursor, "end": offset + len(piece)})
        segments = [part for segment in segments for part in _unquoted_dialogues(segment, text, roles)]
        dialogues = [s for s in segments if s["kind"] in ("dialogue", "thought")]
        narration = [s for s in segments if s["kind"] == "narration"]
        if not piece:
            action = "承接相邻原文已发生的动作、等待或表情，用辅助旁白交代短暂停顿，不推进后文事件。"
        elif dialogues:
            action = "按本格旁白表现动作；由" + "、".join(dict.fromkeys(s["speaker"] for s in dialogues)) + "依容器顺序表达指定内容，气泡尾巴仅指向各自所属人物。"
        else:
            action = "按本格旁白表现动作或反应；没有人物对白，不画任何带尾巴的气泡或空白气泡。"
        panels.append({"scene_no": number, "source_text": piece, "segments": segments, "narration": [s["text"] for s in narration], "dialogues": [{"speaker": s["speaker"], "text": s["text"], "thought": s["kind"] == "thought"} for s in dialogues], "speech_bubble_count": sum(s["kind"] == "dialogue" for s in dialogues), "thought_bubble_count": sum(s["kind"] == "thought" for s in dialogues), "action": action})
        if not segments:
            caption = (last_speaker + "停顿了片刻。") if last_speaker else "气氛停顿了片刻。"
            panels[-1]["narration"] = [caption]
            panels[-1]["auxiliary_narration"] = caption
        if dialogues:
            last_speaker = dialogues[-1]["speaker"]
        offset += len(piece)
    plan = {"version": PLAN_VERSION, "source_body": text, "narrator": roles.narrator, "roles": list(roles.roles.values()), "setting": _setting(text), "panels": panels, "warnings": warnings}
    validate_comic_plan(plan)
    return plan


def validate_comic_plan(plan):
    text = plan["source_body"]
    if "".join(p["source_text"] for p in plan["panels"]) != text:
        raise RuntimeError("分格执行单与正文不一致。")
    for panel in plan["panels"]:
        if "".join(s["source"] for s in panel["segments"]) != panel["source_text"]:
            raise RuntimeError("旁白与对白拆分后丢失或重复原文。")
        for segment in panel["segments"]:
            if text[segment["start"]:segment["end"]] != segment["source"]:
                raise RuntimeError("分格执行单的原文位置不一致。")
            if segment["kind"] in ("dialogue", "thought") and not segment.get("speaker"):
                raise RuntimeError("对白缺少明确说话人。")
        if not panel["dialogues"] and not any(str(t).strip() for t in panel["narration"]):
            raise RuntimeError("每格必须有对白或旁白。")
        if panel.get("auxiliary_narration") and (panel["source_text"] or panel["segments"]):
            raise RuntimeError("本地辅助旁白只能补充原文分格后没有文字的反应格。")


def format_comic_plan(plan, positions):
    """Only container text is printable; source spans stay in the audit plan."""
    lines = ["【角色与场景执行规则（不印字）】", "叙述者“我”对应：" + plan["narrator"]]
    for role in plan["roles"]:
        lines.append(f"角色：{role['name']}；性别：{role['gender']}。外貌、服装各格保持一致，职业与身份只依正文；正文未指定服装时使用普通日常便服。")
    lines.extend(["场景依据：" + plan["setting"]["basis"], "场景：" + plan["setting"]["description"], "【各格文案与画面执行单】"])
    for panel, position in zip(plan["panels"], positions):
        lines.append(f"第{panel['scene_no']}格（{position}）" + ("为辅助旁白反应格" if panel.get("auxiliary_narration") else ""))
        lines.append("画面动作（不印字）：" + panel["action"])
        for index, segment in enumerate(panel["segments"], 1):
            if segment["kind"] == "narration":
                lines.append(f"文字容器{index}／旁白容器（独立无尾；样式与位置继承参考图旁白，参考图无旁白时按其画风设计，不连接人物）：{segment['text']}")
            else:
                label = "思考气泡" if segment["kind"] == "thought" else "对白气泡"
                pointer = "思考小圆点仅连接" if segment["kind"] == "thought" else "尾巴仅指向"
                lines.append(f"文字容器{index}／{label}（所属人物={segment['speaker']}，{pointer}{segment['speaker']}）：{segment['text']}")
        if panel.get("auxiliary_narration"):
            lines.append("文字容器1／旁白容器（独立无尾；样式与位置继承参考图旁白，参考图无旁白时按其画风设计，不连接人物）：" + panel["auxiliary_narration"])
        lines.append(f"本格普通对白气泡数量={panel['speech_bubble_count']}；思考气泡数量={panel['thought_bubble_count']}。不得合并不同所属人物的气泡，未分配对白的人物保持无对白。")
    return "\n".join(lines) + "\n\n"
