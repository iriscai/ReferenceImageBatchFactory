"""Real Tk regression for checkbox clicks and the standard account editor."""
import copy
import json
from pathlib import Path
from contextlib import closing
import sqlite3
import time
import unittest
from unittest.mock import Mock,patch
import picfactory_gui as pg
from multi_reference_picker import ReferenceChecklist
import test_multi_reference_mode as multi_tests


class PickerTests(unittest.TestCase):
    def setUp(self):
        multi_tests.MultiReferenceUITests.setUp(self)
        self.app.root.geometry('1300x900+5000+5000');self.app.root.deiconify()
        self.dialog.geometry('1120x760+5000+5000');self.dialog.deiconify();self.app.root.update()

    def tearDown(self):
        multi_tests.MultiReferenceUITests.tearDown(self)

    def widgets(self,parent):
        yield from multi_tests.MultiReferenceUITests.widgets(self,parent)

    def checks(self,parent=None):
        return [w for w in self.widgets(parent or self.dialog) if isinstance(w,ReferenceChecklist)]

    def button(self,parent,text):
        return next(w for w in self.widgets(parent) if isinstance(w,pg.ttk.Button) and w.cget('text')==text)

    def click_item(self,picker,item):
        picker.tree.see(item);self.app.root.update_idletasks()
        box=picker.tree.bbox(item)
        if not box:
            self.dialog.deiconify();self.app.root.update();box=picker.tree.bbox(item)
        self.assertTrue(box)
        x,y,width,height=box
        picker.tree.event_generate('<Button-1>',x=x+8,y=y+height//2,state=0)
        picker.tree.event_generate('<ButtonRelease-1>',x=x+8,y=y+height//2,state=0)
        self.app.root.update()

    def test_two_plain_clicks_check_two_references_without_modifier(self):
        background,character=self.checks()
        background.set_names([]);character.set_names([])
        items=background.tree.get_children()
        self.click_item(background,items[0]);self.click_item(background,items[1])
        self.assertEqual(len(background.get_names()),2)
        self.assertEqual(background.count.get(),'已选 2 张')
        self.assertTrue(all(background.tree.item(i,'text').startswith('☑ ') for i in items))
        self.button(self.dialog,'保存此账号').invoke()
        self.assertEqual(len(self.new['multi_reference_config']['background_names']),2)
        self.assertEqual(self.new['multi_reference_config']['character_names'],[])
        self.assertEqual(len(self.app.account_generation_binding(self.new)['image_paths']),2)
        self.assertEqual(self.old['generation_mode'],pg.GENERATION_MODE_13)

    def test_search_and_unchecking_keep_hidden_choices_and_click_order(self):
        background,_=self.checks();background.set_names(['形象','背景'])
        background.search.set('背景');time.sleep(.17);self.app.root.update()
        self.assertEqual(background.get_names(),['形象','背景'])
        self.click_item(background,background.tree.get_children()[0])
        self.assertEqual(background.get_names(),['形象'])
        background.search.set('');time.sleep(.17);self.app.root.update()
        self.assertEqual(background.get_names(),['形象'])

    def test_three_clicks_persist_three_references_for_the_generation_binding(self):
        self.dialog.destroy()
        third=Path(self.temp.name)/'第三张.png';third.write_bytes(b'third-original-image')
        self.app.state['reference_images'].append({'name':'第三张','image_path':str(third),'enabled':True})
        self.app.open_multi_reference_config()
        self.dialog=next(w for w in self.app.root.winfo_children() if isinstance(w,pg.tk.Toplevel))
        self.dialog.geometry('1120x760+5000+5000');self.dialog.deiconify();self.app.root.update()
        background,character=self.checks();background.set_names([]);character.set_names([])
        for item in background.tree.get_children():self.click_item(background,item)
        self.assertEqual(background.count.get(),'已选 3 张')
        expected=background.get_names();self.button(self.dialog,'保存此账号').invoke()
        with closing(sqlite3.connect(pg.MATRIX_DB_PATH)) as conn:
            saved=json.loads(conn.execute("SELECT payload FROM app_collections WHERE namespace='wechat_accounts' AND item_key='new'").fetchone()[0])
        self.assertEqual(saved['multi_reference_config']['background_names'],expected)
        self.assertEqual(len(self.app.account_generation_binding(saved)['image_paths']),3)

    def open_standard_editor(self,account):
        self.dialog.destroy()
        for child in self.app.main.winfo_children():child.destroy()
        fields=[{'key':'uuid','label':'UUID','readonly':True}, {'key':'name','label':'名称','required':True},
                {'key':'generation_mode','label':'生图方式','type':'combo','values':list(pg.GENERATION_MODES)},
                {'key':'reference_name','label':'参考图','type':'combo','values':lambda:self.app.reference_image_names()}]
        self.app.render_collection_list_page(self.app.main,'测试账号','wechat_accounts',fields,initialize_missing=False,initialize_metadata=False)
        tree=next(w for w in self.widgets(self.app.main) if isinstance(w,pg.ttk.Treeview))
        tree.focus(account['uuid']);tree.selection_set(account['uuid'])
        tree.event_generate('<<TreeviewSelect>>')
        # Click the real row's edit action, just as the user does.
        self.app.root.update();tree.xview_moveto(1);self.app.root.update_idletasks()
        box=tree.bbox(account['uuid'],tree['columns'][-1]);self.assertTrue(box)
        x,y,width,height=box
        tree.event_generate('<Button-1>',x=x+12,y=y+height//2,state=0)
        tree.event_generate('<ButtonRelease-1>',x=x+12,y=y+height//2,state=0)
        self.app.root.update()
        self.dialog=next(w for w in self.app.root.winfo_children() if isinstance(w,pg.tk.Toplevel))
        self.app.root.update()
        return self.dialog

    def test_standard_multi_account_editor_opens_picker_and_saves_draft_only_on_save(self):
        original=copy.deepcopy(self.new)
        editor=self.open_standard_editor(self.new)
        button=self.button(editor,'勾选多张参考图…')
        self.assertTrue(button.winfo_ismapped())
        button.invoke();self.app.root.update()
        picker=next(w for w in editor.winfo_children() if isinstance(w,pg.tk.Toplevel))
        background,character=self.checks(picker)
        background.set_names(['背景','形象']);character.set_names([])
        self.button(picker,'确定选择').invoke()
        self.assertEqual(self.new,original)
        self.app.save_state=Mock()
        self.button(editor,'保存').invoke()
        self.assertEqual(self.new['multi_reference_config']['background_names'],['背景','形象'])
        self.assertEqual(self.new['reference_name'],'原字段保留')
        self.assertEqual(self.old['generation_mode'],pg.GENERATION_MODE_13)

    def test_cancel_standard_editor_does_not_change_multi_config(self):
        original=copy.deepcopy(self.new)
        editor=self.open_standard_editor(self.new)
        self.button(editor,'勾选多张参考图…').invoke();self.app.root.update()
        picker=next(w for w in editor.winfo_children() if isinstance(w,pg.tk.Toplevel))
        background,character=self.checks(picker)
        background.set_names(['背景','形象']);character.set_names([])
        self.button(picker,'确定选择').invoke()
        self.button(editor,'取消').invoke()
        self.assertEqual(self.new,original)

    def test_other_modes_keep_single_combobox_and_own_reference_value(self):
        editor=self.open_standard_editor(self.old)
        old_combo=next(w for w in self.widgets(editor) if isinstance(w,pg.ttk.Combobox) and w.get()=='背景')
        self.assertTrue(old_combo.winfo_ismapped())
        self.assertFalse(self.button(editor,'勾选多张参考图…').winfo_ismapped())
        self.app.save_state=Mock();self.button(editor,'保存').invoke()
        self.assertEqual(self.old['reference_name'],'背景')
        self.assertNotIn('multi_reference_config',self.old)


if __name__=='__main__':unittest.main()
