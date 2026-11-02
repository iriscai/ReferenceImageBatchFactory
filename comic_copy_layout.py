"""Keep original comic copy intact while selecting narrative panel boundaries.

This is a local punctuation/reaction heuristic, not a language-model planner.
It never cuts inside quoted dialogue or moves text between finished panels.
"""

import re


_QUOTES = {"“": "”", "‘": "’", "「": "」", "『": "』", '"': '"', "'": "'"}
_CLOSERS = "”’」』\"'"
_STOPS = "。！？!?；;"
_REACTION = re.compile(
    r"(?:没|未).{0,4}(?:答|接|说).{0,4}(?:上|出|话)"
    r"|愣住|停住|怔住|呆住|僵住|卡住|沉默|哑口无言|无言以对"
    r"|说不出话|答不上来|没接话|没吭声|不吭声|不说话|没说话"
    r"|一时语塞|张了张嘴|面面相觑|没有动|没动|空气.{0,3}安静"
)


def _copy_units(text: str) -> list[str]:
    """Split outside quotes; keep a colon-introduced, unquoted utterance whole."""
    units: list[str] = []
    stack: list[str] = []
    start = 0
    unquoted_speech = False
    for index, char in enumerate(text):
        # Apostrophes within English words are not quotation boundaries.
        apostrophe = (
            char == "'" and index > 0 and index + 1 < len(text)
            and text[index - 1].isalnum() and text[index + 1].isalnum()
        )
        closed_quote = False
        if not apostrophe:
            if stack and char == stack[-1]:
                stack.pop()
                closed_quote = not stack
            elif char in _QUOTES:
                stack.append(_QUOTES[char])
        if stack:
            continue
        piece = text[start:index + 1]
        remaining = text[index + 1:]
        if char in "：:":
            unquoted_speech = remaining.lstrip()[:1] not in _QUOTES
        if char in "，," and re.search(r"(?:说|问|道|喊|答|解释|追问|反问)[，,]$", piece):
            unquoted_speech = True
        boundary = char in _STOPS or char == "\n"
        if char == "\n" and piece.rstrip().endswith(("：", ":")):
            # A wrapped speaker label still belongs to its following utterance.
            boundary = False
        if char in "，," and not unquoted_speech:
            boundary = True
        quote_body = piece.rstrip(_CLOSERS)
        if closed_quote and quote_body and quote_body[-1] in _STOPS:
            # Include a following comma/stop in the same unit, and retain
            # constructions such as 她问“你愿意吗？”的时候.
            following = remaining[:1]
            continuation = remaining.startswith(("的", "地", "得", "时", "后", "前", "里", "中"))
            if not continuation and (not following or following not in "，,。！？!?；;：:\n"):
                boundary = True
        if boundary:
            if piece.strip() or not units:
                units.append(piece)
            else:
                units[-1] += piece
            start = index + 1
            unquoted_speech = False
    if start < len(text):
        units.append(text[start:])
    return units


def _is_reaction(piece: str) -> bool:
    text = piece.strip()
    return (
        len(text) <= 40 and not any(char in text for char in "“”‘’「」『』\"：:")
        and bool(_REACTION.search(text))
    )


def _boundary_strength(left: str, right: str) -> int:
    ending = left.rstrip().rstrip(_CLOSERS)
    strength = 12 if ending and ending[-1] in _STOPS else 2
    if "\n" in left[-2:]:
        strength += 8
    # A short reaction is a narrative beat, not spare space to fill with the
    # neighboring speaker's words. Protect both of its boundaries.
    if _is_reaction(left):
        strength += 20
    if _is_reaction(right):
        strength += 20
    return strength


def split_comic_copy(body: str, count: int) -> list[str]:
    """Return ordered, lossless slices, preserving dialogue and reaction beats.

    When there are too few safe units, empty panels represent silent reactions.
    With excess units, merge adjacent units at the weakest narrative boundaries.
    Length only resolves ties between equally strong boundary choices.
    """
    count = max(1, int(count))
    text = str(body or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    if not text:
        return [""] * count
    units = _copy_units(text)
    size = len(units)
    if size <= count:
        frames = [""] * count
        for index, unit in enumerate(units):
            position = round(index * (count - 1) / (size - 1)) if size > 1 else 0
            frames[position] = unit
    else:
        prefix = [0]
        for unit in units:
            prefix.append(prefix[-1] + len(unit))
        strengths = [_boundary_strength(units[i - 1], units[i]) for i in range(1, size)]
        # Dynamic programming makes the fixed panel count a global choice.
        # The semantic score is compared first, so length cannot displace a
        # better dialogue/reaction boundary merely to equalize character counts.
        states = {0: ((0, 0), ())}
        for panel in range(1, count + 1):
            next_states = {}
            for end in range(panel, size - (count - panel) + 1):
                best = None
                for start, (score, cuts) in states.items():
                    if start >= end:
                        continue
                    length = prefix[end] - prefix[start]
                    candidate = (
                        score[0] + (strengths[start - 1] if start else 0),
                        score[1] - length * length,
                    )
                    if best is None or candidate > best[0]:
                        best = (candidate, cuts + (end,))
                if best is not None:
                    next_states[end] = best
            states = next_states
        cuts = (0,) + states[size][1]
        frames = ["".join(units[cuts[i]:cuts[i + 1]]) for i in range(count)]
    if len(frames) != count or "".join(frames) != text:
        raise RuntimeError("六宫格参考图生图分格后正文与原文不一致。")
    return frames
