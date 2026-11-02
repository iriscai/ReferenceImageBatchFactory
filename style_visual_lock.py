"""Quote the bound template's own visual definitions for every character."""
import re


def visual_lock(style):
    text = style.get('full_prompt') or style.get('content') or ''
    chunks = re.findall(r'(【[^】]+】)([^【]*)', text)
    selected = []
    for header, body in chunks:
        if any(key in header for key in ('版式','参考','叙事','连续性','格内完整')):
            continue
        if any(key in header for key in ('人物','五官','头发','线条','媒介','背景','色彩','气泡','配色','禁止')):
            selected.append(header + body.strip())
    return ('【画风最高优先级：逐项采用当前账号模板】\n' + '\n'.join(selected) +
            '\n以上人物比例、脸型、鼻眼嘴、线条、肤色留白、背景和色彩范围约束每一个角色，包括女性、妻子、母亲、女友和监考者。'
            '除非模板明确规定男女有不同画法，不允许只给男性执行夸张造型，女性另用普通动漫或美型人像。'
            '原模板要求少色、肤色留白或背景留白时严格执行，不因故事场景或人物性别补肉色、衣服满涂、成片背景或精细光影。'
            '下方身份与动作只决定剧情，不能覆盖上述画法。文字严格按给定字形逐字绘制，不得简繁转换。')
