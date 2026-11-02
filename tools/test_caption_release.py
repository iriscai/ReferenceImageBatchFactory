"""Release contracts: reference adaptation must not change style-mode prompts."""
import copy
import hashlib
import json
from pathlib import Path
import sys
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.dont_write_bytecode=True
sys.path.insert(0,str(ROOT))
import comic_prompt_planner as planner
import six_grid_style_prompt as style
from reference_prompt_baseline import PROJECT13_REFERENCE_PROMPT
from strong_reference_prompt import NARRATION_REFERENCE_RULE
from comic_story_plan import build_comic_plan, format_comic_plan


class CaptionReleaseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.contract=json.loads((Path(__file__).parent/'fixtures/style_v4_contract.json').read_text(encoding='utf-8'))

    def test_style_prompt_keeps_frozen_v4_contract(self):
        c=self.contract
        result=style.generate_style_prompt(c['style'],c['source'],lambda _:json.dumps(c['plan'],ensure_ascii=False))
        self.assertEqual(hashlib.sha256(result['prompt'].encode()).hexdigest(),c['v4_prompt_sha256'])
        self.assertEqual(hashlib.sha256(style.planning_request(c['source']).encode()).hexdigest(),c['v4_planning_request_sha256'])
        self.assertNotIn(NARRATION_REFERENCE_RULE,result['prompt'])

    def test_original_strong_reference_rule_is_preserved(self):
        self.assertEqual(hashlib.sha256(PROJECT13_REFERENCE_PROMPT.encode()).hexdigest(),
                         'd7988bc7e581c09b1c04967c785073f6f9579dcea44349571b9db17f78e7b542')

    def test_reference_prompt_includes_adaptive_caption_policy(self):
        c=self.contract
        plan=dict(c['plan'],title='测试',note='原文分镜',source_body=c['source'])
        prompt=planner.render_semantic_prompt(plan)
        self.assertTrue(prompt.startswith(PROJECT13_REFERENCE_PROMPT))
        self.assertIn(NARRATION_REFERENCE_RULE,prompt)
        self.assertNotIn('独立短矩形旁白框数量',prompt)
        self.assertNotIn('本格左上方的短矩形',prompt)

    def test_local_formatter_does_not_force_caption_rectangle(self):
        plan=build_comic_plan('妻子说：“好了。”丈夫点了点头。',6)
        text=format_comic_plan(plan,[str(i) for i in range(6)])
        self.assertNotIn('旁白框（矩形或',text)
        self.assertIn('样式与位置继承参考图旁白',text)

    def test_screen_text_cannot_replace_required_caption(self):
        panels=copy.deepcopy(self.contract['plan']['panels'])
        panels[0].update(dialogue=[],narration='',screens=[['手机','示例']])
        with self.assertRaises(planner.ComicPlanError):planner.require_panel_copy(panels)

    def test_unknown_speaker_is_rejected(self):
        c=self.contract;plan=copy.deepcopy(c['plan'])
        plan['panels'][0]['dialogue']=[['不存在的角色','等一下。']]
        with self.assertRaises(ValueError):style.validate(plan,c['source'])

    def test_added_numeric_fact_is_rejected(self):
        c=self.contract;plan=copy.deepcopy(c['plan'])
        plan['panels'][0]['narration']='花了987654321元。'
        with self.assertRaises(ValueError):style.validate(plan,c['source'])


if __name__=='__main__':unittest.main()
