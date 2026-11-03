"""Style transfer must not import reference identities or pictured quotations."""
import unittest
import picfactory_gui as pg


class MultiReferenceContentGuardTests(unittest.TestCase):
    def setUp(self):
        self.app=pg.PicFactoryGUI.__new__(pg.PicFactoryGUI)
        self.body='游客在车上发现一张小鸟车贴，上面写着“慢慢来，别着急”。他拍下这张贴纸。'
        self.scene='游客再次拍摄车贴，保留原标语。'

    def prompt(self,roles=None,character=''):
        return self.app.build_multi_reference_frame_prompt(2,2,'拍下贴纸','他拍下这张贴纸。',self.scene,
            ['画风甲','样本乙'],'1080x1440',character=character,reference_roles=roles,source_body=self.body)

    def test_all_references_are_style_only_even_with_legacy_character_role(self):
        text=self.prompt([{'name':'画风甲','role':'background'},{'name':'样本乙','role':'character'}])
        self.assertEqual(text.count('用途：仅参考画风，不提供人物、故事内容或文字'),2)
        self.assertIn('无论历史配置给图片标注过什么用途',text)
        self.assertNotIn('人物按形象图锁定身份',text)
        self.assertNotIn('脸、发型、衣服以形象参考图为准',text)
        self.assertNotIn('存在用途清单明确标为',text)

    def test_legacy_account_character_prompt_is_not_injected(self):
        text=self.prompt(character='把第二张参考图里的蓝衣老主播当作主人公')
        self.assertNotIn('蓝衣老主播',text)
        self.assertNotIn('账号人物身份与外貌补充',text)

    def test_original_story_resolves_generic_sticker_caption_and_portrait(self):
        text=self.prompt()
        self.assertIn(self.body,text)
        self.assertIn('慢慢来，别着急',text)
        self.assertIn('全文不是本张的展示文案',text)
        self.assertIn('不能用参考图人物或文字填补指代',text)
        self.assertIn('车贴肖像、海报、照片、手机屏幕',text)
        self.assertIn('标题、口号、字幕、标志、页码',text)

    def test_style_fidelity_and_current_frame_text_are_still_required(self):
        text=self.prompt()
        self.assertIn('绘制方式的最高依据',text)
        self.assertIn('笔触、色彩、光影',text)
        self.assertIn('本张文案逐字保留',text)
        self.assertIn('只画本张文案和本张场景',text)

    def test_cast_planner_does_not_presume_a_character_reference_exists(self):
        text=self.app.multi_reference_supporting_cast_prompt('新故事',self.body,'历史固定主播必须照搬参考图')
        self.assertNotIn('主角色已经有形象参考图',text)
        self.assertNotIn('历史固定主播',text)
        self.assertIn('主角色与副角色的身份只能取本篇标题和正文',text)

    def test_storyboard_prompt_removes_legacy_character_injection_and_resolves_proxies(self):
        text=self.app.multi_reference_storyboard_split_prompt({'prompt_content':'分镜规则：${人物}'},'新故事',self.body,'复制旧参考人物')
        self.assertNotIn('复制旧参考人物',text)
        self.assertIn('原标语',text)
        self.assertIn('不能只写‘完整标语’等占位描述',text)


if __name__=='__main__':unittest.main()
