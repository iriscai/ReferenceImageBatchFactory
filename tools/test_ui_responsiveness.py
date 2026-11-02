"""Real Tk interaction regressions using isolated state and synthetic accounts."""
import json
from contextlib import closing
from pathlib import Path
import sqlite3
import sys
import tempfile
import time
import types
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.dont_write_bytecode=True;sys.path.insert(0,str(ROOT))
import picfactory_gui as pg


class AccountCanvasTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='account_canvas_test_');folder=Path(self.temp.name)
        self.globals=patch.multiple(pg,APP_DIR=folder,STATE_PATH=folder/'state.json',MATRIX_DB_PATH=folder/'matrix.db',PACKAGED_MATRIX_DB_PATH=folder/'absent.db',LOG_DIR=folder/'logs',_MATRIX_DB_READY=False,_DB_COLLECTION_DIGESTS={})
        self.globals.start()
        real=pg.tk.Tk
        def hidden(*args,**kwargs):root=real(*args,**kwargs);root.withdraw();return root
        with patch.object(pg.tk,'Tk',hidden):self.app=pg.PicFactoryGUI()
        for token in self.app.root.tk.call('after','info'):self.app.root.after_cancel(token)
        self.app.state['wechat_accounts']=[{'uuid':f'test-{i:03d}','account_id':f'test-{i:03d}','name':f'测试账号{i:03d}',
             'enabled':True,'owner_user':'测试','generation_mode':pg.GENERATION_MODE_13 if i%2 else pg.GENERATION_MODE_GRID_STYLE}
             for i in range(300)]
        self.app.account_generation_defaults['selected_account_ids']=[]
        self.app.current_workspace='account_generation';self.app.refresh_all();self.app.root.update_idletasks()

    def tearDown(self):
        for token in self.app.root.tk.call('after','info'):self.app.root.after_cancel(token)
        self.app.root.destroy();self.globals.stop();self.temp.cleanup()

    def test_cards_use_canvas_items_instead_of_thousands_of_widgets(self):
        canvas=self.app.account_generation_cards_canvas
        self.assertEqual(len(canvas.winfo_children()),0)
        self.assertEqual(len(canvas.find_all()),300*4)

    def test_click_updates_selection_without_rebuilding_cards(self):
        canvas=self.app.account_generation_cards_canvas;items=canvas.find_all()
        account=self.app._account_card_rows[0]
        self.app._on_account_generation_card_click(types.SimpleNamespace(x=2,y=2))
        self.assertIn(account['uuid'],self.app.account_generation_selected_account_ids)
        self.assertEqual(items,canvas.find_all())
        self.app._on_account_generation_card_click(types.SimpleNamespace(x=2,y=2))
        self.assertNotIn(account['uuid'],self.app.account_generation_selected_account_ids)
        self.assertEqual(items,canvas.find_all())

    def test_mode_filter_keeps_selection_and_draws_only_matching_cards(self):
        self.app.account_generation_selected_account_ids={'test-001'}
        self.app.account_generation_mode_filter_var.set(pg.GENERATION_MODE_GRID_STYLE)
        self.app.account_generation_refresh_account_list()
        self.assertEqual(len(self.app._account_card_rows),150)
        self.assertEqual(len(self.app.account_generation_cards_canvas.find_all()),600)
        self.assertEqual(self.app.account_generation_selected_account_ids,{'test-001'})

    def test_saving_selection_does_not_rewrite_business_collections(self):
        with closing(sqlite3.connect(pg.MATRIX_DB_PATH)) as db:before=db.execute("SELECT namespace,item_key,payload,sort_order FROM app_collections WHERE namespace != 'app_settings' ORDER BY namespace,item_key").fetchall()
        self.app.account_generation_selected_account_ids={'test-005'}
        self.app.save_account_generation_config()
        with closing(sqlite3.connect(pg.MATRIX_DB_PATH)) as db:
            after=db.execute("SELECT namespace,item_key,payload,sort_order FROM app_collections WHERE namespace != 'app_settings' ORDER BY namespace,item_key").fetchall()
        self.assertEqual(before,after)
        self.assertEqual(self.app.account_generation_defaults['selected_account_ids'],['test-005'])

    def test_fast_search_burst_refreshes_once_and_ignores_closed_table(self):
        owner=pg.tk.Canvas(self.app.root);calls=[]
        for i in range(3):self.app.queue_list_refresh(owner,lambda i=i:calls.append(i))
        deadline=time.monotonic()+0.25
        while time.monotonic()<deadline:self.app.root.update();time.sleep(0.005)
        self.assertEqual(calls,[2])
        self.app.queue_list_refresh(owner,lambda:calls.append('closed'));owner.destroy()
        deadline=time.monotonic()+0.2
        while time.monotonic()<deadline:self.app.root.update();time.sleep(0.005)
        self.assertEqual(calls,[2])


if __name__=='__main__':unittest.main()
