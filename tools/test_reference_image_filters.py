"""Reference metadata filters in both multi-image selection paths."""
import copy
from contextlib import closing
import json
import sqlite3
import time
import unittest
from unittest.mock import Mock
import picfactory_gui as pg
import test_multi_reference_picker as picker_tests
from multi_reference_picker import ReferenceChecklist,filter_reference_images


class ReferenceFilterLogicTests(unittest.TestCase):
    def setUp(self):
        self.records=[{'name':'背景','ref_id':'REF-BG','category':'军事','tags':'水墨,历史','description':'钢笔笔触'},
                      {'name':'形象','ref_id':'REF-CHAR','category':'人物','tags':['固定角色']},
                      {'name':'城市','ref_id':'REF-CITY','category':'房产','tags':'水墨'},
                      {'name':'未整理','enabled':True},
                      {'name':'停用','category':'军事','tags':'水墨','enabled':False}]

    def test_reference_group_tag_and_text_search_combine(self):
        self.assertEqual(filter_reference_images(self.records,'军事','水墨','REF-bg'),[self.records[0]])
        self.assertEqual(filter_reference_images(self.records,'军事','水墨','笔触'),[self.records[0]])
        self.assertEqual(filter_reference_images(self.records,'军事','固定角色'),[])
        self.assertEqual(filter_reference_images(self.records,'全部分组','水墨'),[self.records[0],self.records[2]])

    def test_ungrouped_untagged_and_disabled_records_are_handled_without_mutation(self):
        before=copy.deepcopy(self.records)
        self.assertEqual(filter_reference_images(self.records,'未分组','未标记'),[self.records[3]])
        self.assertEqual(self.records,before)


class ReferenceFilterUITests(unittest.TestCase):
    def setUp(self):
        picker_tests.PickerTests.setUp(self);self.dialog.destroy()
        refs=self.app.state['reference_images']
        refs[0].update(uuid='ref-bg',ref_id='REF-BG',category='军事',tags='水墨,历史',description='钢笔笔触')
        refs[1].update(uuid='ref-char',ref_id='REF-CHAR',category='人物',tags='固定角色',description='固定人物')
        from pathlib import Path
        third=Path(self.temp.name)/'city.png';third.write_bytes(b'city-original')
        refs.append({'uuid':'ref-city','name':'城市','ref_id':'REF-CITY','image_path':str(third),'enabled':True,'category':'房产','tags':'水墨'})
        self.new.update(group='账号组不应出现在选图分组',tags='账号标签不应出现')
        self.app.open_multi_reference_config()
        self.dialog=next(w for w in self.app.root.winfo_children() if isinstance(w,pg.tk.Toplevel))
        self.dialog.geometry('1120x760+5000+5000');self.dialog.deiconify();self.app.root.update()

    def tearDown(self):
        picker_tests.PickerTests.tearDown(self)

    def widgets(self,parent):
        yield from picker_tests.PickerTests.widgets(self,parent)

    def checks(self,parent=None):
        return [w for w in self.widgets(parent or self.dialog) if isinstance(w,ReferenceChecklist)]

    def button(self,parent,text):
        return next(w for w in self.widgets(parent) if isinstance(w,pg.ttk.Button) and w.cget('text')==text)

    def choose(self,combo,value):
        combo.set(value);combo.event_generate('<<ComboboxSelected>>');self.app.root.update()

    def test_choices_come_from_reference_images_not_account_metadata(self):
        background,character=self.checks()
        for picker in [background,character]:
            self.assertIn('军事',picker.group_combo['values'])
            self.assertIn('水墨',picker.tag_combo['values'])
            self.assertNotIn(self.new['group'],picker.group_combo['values'])
            self.assertNotIn(self.new['tags'],picker.tag_combo['values'])

    def test_reference_group_tag_and_id_search_filter_each_column_independently(self):
        background,character=self.checks()
        self.choose(background.group_combo,'军事');self.choose(background.tag_combo,'水墨')
        background.search.set('ref-bg');time.sleep(.17);self.app.root.update()
        self.assertEqual(list(background.visible.values()),['背景'])
        self.assertEqual(len(character.visible),3)
        background.search.set('not-found');time.sleep(.17);self.app.root.update()
        self.assertEqual(background.visible,{})
        background.reset_filters();self.app.root.update()
        self.assertEqual(len(background.visible),3)

    def test_selection_from_other_groups_survives_search_and_saving(self):
        original_old=copy.deepcopy(self.old)
        background,character=self.checks()
        background.set_names(['城市','背景']);character.set_names(['形象'])
        self.choose(background.group_combo,'军事')
        self.assertEqual(list(background.visible.values()),['背景'])
        self.assertEqual(background.get_names(),['城市','背景'])
        self.button(self.dialog,'保存此账号').invoke()
        with closing(sqlite3.connect(pg.MATRIX_DB_PATH)) as c:
            saved=json.loads(c.execute("SELECT payload FROM app_collections WHERE namespace='wechat_accounts' AND item_key='new'").fetchone()[0])
        self.assertEqual(saved['multi_reference_config']['background_names'],['城市','背景'])
        self.assertEqual(len(self.app.account_generation_binding(saved)['image_paths']),3)
        self.assertEqual(self.old,original_old)

    def test_regular_account_editor_picker_has_the_same_reference_filters(self):
        self.button(self.dialog,'取消').invoke()
        self.app.open_multi_reference_picker(self.app.root,self.new['multi_reference_config'],lambda _:None)
        picker=next(w for w in self.app.root.winfo_children() if isinstance(w,pg.tk.Toplevel))
        for check in self.checks(picker):
            self.assertIn('房产',check.group_combo['values'])
            self.assertIn('固定角色',check.tag_combo['values'])
        self.button(picker,'取消').invoke()

    def test_cancel_reference_filters_preserves_account_and_reference_records(self):
        before=copy.deepcopy(self.app.state)
        background,_=self.checks();self.choose(background.group_combo,'房产')
        self.choose(background.tag_combo,'水墨');background.set_names(['城市'])
        self.button(self.dialog,'取消').invoke()
        self.assertEqual(self.app.state,before)

    def test_reference_tag_editor_persists_only_metadata_and_keeps_generation_binding(self):
        self.dialog.destroy()
        for widget in self.app.main.winfo_children():widget.destroy()
        old_accounts=copy.deepcopy(self.app.state['wechat_accounts'])
        binding=self.app.account_generation_binding(self.new)
        self.app.prepare_undo=Mock()
        self.app.current_workspace='reference_management'
        self.app.render_reference_management_workspace();self.app.root.update()
        tree=next(w for w in self.widgets(self.app.main) if isinstance(w,pg.ttk.Treeview))
        tree.selection_set('ref-bg');tree.event_generate('<<TreeviewSelect>>');self.app.root.update()
        label=next(w for w in self.widgets(self.app.main) if isinstance(w,pg.ttk.Label) and w.cget('text')=='标签（逗号分隔）')
        entry=next(w for w in label.master.grid_slaves(row=7,column=1) if isinstance(w,pg.ttk.Entry))
        entry.delete(0,'end');entry.insert(0,'水墨,军事')
        self.button(self.app.main,'保存修改').invoke()
        with closing(sqlite3.connect(pg.MATRIX_DB_PATH)) as c:
            value=json.loads(c.execute("SELECT payload FROM app_collections WHERE namespace='reference_images' AND item_key='ref-bg'").fetchone()[0])
        self.assertEqual(value['tags'],'水墨,军事')
        self.assertEqual(value['category'],'军事');self.assertEqual(value['description'],'钢笔笔触')
        self.assertEqual(self.app.state['wechat_accounts'],old_accounts)
        self.assertEqual(self.app.account_generation_binding(self.new),binding)


if __name__=='__main__':unittest.main()
