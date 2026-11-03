"""Combined account filters must never save the wrong account or lose a draft."""
import copy
from contextlib import closing
import json
import sqlite3
import time
import unittest
import picfactory_gui as pg
import test_multi_reference_picker as picker_tests
from multi_reference_picker import ReferenceChecklist, filter_multi_reference_accounts


class AccountFilterLogicTests(unittest.TestCase):
    def setUp(self):
        self.accounts=[{'name':'Alpha','account_id':'gh_A','group':'A','tags':'军事_1102, 常用'},
                       {'name':'Beta','account_id':'gh_B','group':'A','tags':'国际；常用'},
                       {'name':'Gamma','account_id':'gh_C','group':'B','tags':'军事_1102'},
                       {'name':'Empty','account_id':'gh_D','group':'','tags':''}]

    def test_group_tag_and_case_insensitive_name_or_id_combine(self):
        self.assertEqual(filter_multi_reference_accounts(self.accounts,'A','军事_1102','GH_a'),[self.accounts[0]])
        self.assertEqual(filter_multi_reference_accounts(self.accounts,'A','常用','BETA'),[self.accounts[1]])
        self.assertEqual(filter_multi_reference_accounts(self.accounts,'B','国际',''),[])
        self.assertEqual(filter_multi_reference_accounts(self.accounts,'A','军事',''),[])

    def test_ungrouped_untagged_and_empty_result_do_not_mutate_records(self):
        old=copy.deepcopy(self.accounts)
        self.assertEqual(filter_multi_reference_accounts(self.accounts,'未分组','未标记'),[self.accounts[3]])
        self.assertEqual(filter_multi_reference_accounts(self.accounts,keyword='not-present'),[])
        self.assertEqual(self.accounts,old)


class AccountFilterUITests(unittest.TestCase):
    def setUp(self):
        picker_tests.PickerTests.setUp(self)
        self.dialog.destroy()
        self.new.update(group='A',tags='军事_1102,常用')
        self.old.update(group='B',tags='生活')
        self.third=dict(copy.deepcopy(self.new),uuid='third',name='GROK_国际',account_id='GH_THIRD',tags='国际')
        self.fourth=dict(copy.deepcopy(self.old),uuid='fourth',name='无分组',account_id='GH_EMPTY',group='',tags='')
        self.app.state['wechat_accounts'].extend([self.third,self.fourth])
        pg.save_db_collection('wechat_accounts',self.app.state['wechat_accounts'])
        self.app.open_multi_reference_config()
        self.dialog=next(w for w in self.app.root.winfo_children() if isinstance(w,pg.tk.Toplevel))
        self.dialog.geometry('1120x760+5000+5000');self.dialog.deiconify();self.app.root.update()
        combos=[w for w in self.widgets(self.dialog) if isinstance(w,pg.ttk.Combobox)]
        self.group=next(w for w in combos if tuple(w['values'])[0]=='全部分组')
        self.tag=next(w for w in combos if tuple(w['values'])[0]=='全部标签')
        self.combo=next(w for w in combos if '[' in str(w['values']))
        self.query=next(w for w in self.group.master.winfo_children() if isinstance(w,pg.ttk.Entry) and not isinstance(w,pg.ttk.Combobox))

    def tearDown(self):
        picker_tests.PickerTests.tearDown(self)

    def widgets(self,parent):
        yield from picker_tests.PickerTests.widgets(self,parent)

    def checks(self):
        return [w for w in self.widgets(self.dialog) if isinstance(w,ReferenceChecklist)]

    def button(self,text):
        return next(w for w in self.widgets(self.dialog) if isinstance(w,pg.ttk.Button) and w.cget('text')==text)

    def choose(self,combo,value):
        combo.set(value);combo.event_generate('<<ComboboxSelected>>');self.app.root.update()

    def search(self,text):
        self.query.delete(0,'end');self.query.insert(0,text);time.sleep(.17);self.app.root.update()

    def test_live_combined_filters_and_reset_show_expected_accounts(self):
        self.choose(self.group,'A');self.assertEqual(len(self.combo['values']),2)
        self.choose(self.tag,'国际');self.assertEqual(len(self.combo['values']),1)
        self.assertIn('GH_THIRD',self.combo['values'][0])
        self.search('gh_third');self.assertEqual(len(self.combo['values']),1)
        self.search('not-found');self.assertEqual(self.combo['values'],'')
        self.assertEqual(str(self.button('保存此账号')['state']),'disabled')
        self.button('重置筛选').invoke();self.app.root.update()
        self.assertEqual(len(self.combo['values']),4)
        self.assertEqual(self.query.get(),'')

    def test_same_selected_account_keeps_unsaved_reference_choices_while_filtering(self):
        background,character=self.checks();background.set_names(['背景','形象']);character.set_names([])
        self.choose(self.group,'A');self.search('NEW')
        self.assertEqual(background.get_names(),['背景','形象'])
        self.assertEqual(character.get_names(),[])
        self.assertEqual(self.combo.current(),0)

    def test_filtered_out_selection_cannot_save_and_draft_restores_on_reselection(self):
        original=copy.deepcopy(self.app.state['wechat_accounts'])
        background,character=self.checks();background.set_names(['背景','形象']);character.set_names([])
        self.choose(self.group,'B')
        self.assertEqual(self.combo.get(),'')
        self.assertEqual(str(self.button('保存此账号')['state']),'disabled')
        self.button('保存此账号').invoke()
        self.assertEqual(self.app.state['wechat_accounts'],original)
        self.button('重置筛选').invoke();self.combo.current(1);self.combo.event_generate('<<ComboboxSelected>>');self.app.root.update()
        self.assertEqual(background.get_names(),['背景','形象'])
        self.assertEqual(character.get_names(),[])

    def test_save_after_filter_updates_the_selected_uuid_not_original_list_index(self):
        original=copy.deepcopy(self.app.state['wechat_accounts'])
        self.choose(self.group,'A');self.choose(self.tag,'国际')
        self.combo.current(0);self.combo.event_generate('<<ComboboxSelected>>');self.app.root.update()
        background,character=self.checks();background.set_names(['背景','形象']);character.set_names([])
        self.button('保存此账号').invoke()
        with closing(sqlite3.connect(pg.MATRIX_DB_PATH)) as c:
            stored={k:json.loads(raw) for k,raw in c.execute("SELECT item_key,payload FROM app_collections WHERE namespace='wechat_accounts'")}
        for row in original:
            if row['uuid']!='third':self.assertEqual(stored[row['uuid']],row)
        self.assertEqual(stored['third']['multi_reference_config']['background_names'],['背景','形象'])
        self.assertEqual(stored['third']['group'],'A');self.assertEqual(stored['third']['tags'],'国际')


if __name__=='__main__':unittest.main()
