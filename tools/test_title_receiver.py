"""Protocol/rollback/idempotency regressions using isolated SQLite databases."""
from contextlib import closing
import copy
import json
from pathlib import Path
import sqlite3
import tempfile
import threading
import time
import unittest
from unittest.mock import Mock,patch
import picfactory_gui as pg
import title_library_bridge as bridge


class ReceiverTests(unittest.TestCase):
    def setUp(self):
        self.storage=tempfile.TemporaryDirectory();self.addCleanup(self.storage.cleanup)
        folder=Path(self.storage.name);self.db=folder/'matrix.db'
        self.context=patch.multiple(pg,APP_DIR=folder,MATRIX_DB_PATH=self.db,STATE_PATH=folder/'state.json',
            PACKAGED_MATRIX_DB_PATH=folder/'none.db',_MATRIX_DB_READY=False,_DB_COLLECTION_DIGESTS={})
        self.context.start();self.addCleanup(self.context.stop);pg.ensure_matrix_db()
        with closing(sqlite3.connect(self.db)) as conn:
            conn.execute(bridge.INBOX_SQL);conn.commit()
        self.state={'title_library':[],'wechat_accounts':[{'uuid':'account','generation_mode':pg.GENERATION_MODE_MULTI_REFERENCE,
            'multi_reference_config':{'background_names':['bg'],'character_names':['character']}}]}
        self.account_before=copy.deepcopy(self.state['wechat_accounts'])

    def row(self,identity='new',**kwargs):
        return dict(uuid=identity,title='标题'+identity,body='正文第一段。\n\n正文第二段。'+identity,
                    category='国际',status='启用',used=False,used_at='',source_app='material-comic-workbench',**kwargs)

    def queue(self,delivery,payload):
        with closing(sqlite3.connect(self.db)) as conn,conn:
            conn.execute('INSERT INTO comic_article_inbox(delivery_id,payload,created_at) VALUES(?,?,?)',
                         (delivery,json.dumps(payload,ensure_ascii=False),time.time()))

    def receive(self):
        return bridge.receive_pending(self.state,self.db,process_checked=True)

    def test_receipt_matches_actual_row_preserves_newlines_and_account_modes(self):
        value=self.row();self.queue('delivery',value);titles=self.state['title_library']
        self.assertEqual(self.receive(),1);self.assertIs(self.state['title_library'],titles)
        self.assertEqual(titles,[value]);self.assertEqual(self.state['wechat_accounts'],self.account_before)
        with closing(sqlite3.connect(self.db)) as conn:
            state,key,error,completed=conn.execute('SELECT state,target_key,error,completed_at FROM comic_article_inbox').fetchone()
            stored=json.loads(conn.execute("SELECT payload FROM app_collections WHERE namespace='title_library' AND item_key=?",(key,)).fetchone()[0])
        self.assertEqual((state,error),('pushed',''));self.assertGreater(completed,0);self.assertEqual(stored,value)

    def test_duplicate_delivery_reuses_consumed_record_without_resetting_it(self):
        value=self.row('existing');value.update(status='停用',used=True,used_at='consumed-time')
        pg.save_db_collection('title_library',[value]);self.state['title_library']=[copy.deepcopy(value)]
        new=dict(value,uuid='other',status='启用',used=False,used_at='');self.queue('one',new);self.queue('two',new)
        self.assertEqual(self.receive(),2);self.assertEqual(self.state['title_library'],[value])
        self.assertEqual(self.receive(),0)
        with closing(sqlite3.connect(self.db)) as conn:
            self.assertEqual(conn.execute("SELECT count(*) FROM app_collections WHERE namespace='title_library'").fetchone()[0],1)
            self.assertEqual({r[0] for r in conn.execute('SELECT target_key FROM comic_article_inbox')},{'existing'})

    def test_uuid_collision_preserves_user_edit_and_returns_new_actual_id(self):
        old=self.row('same');pg.save_db_collection('title_library',[old]);self.state['title_library']=[old]
        new=dict(old,body='另一份新正文');self.queue('collision',new)
        self.assertEqual(self.receive(),1)
        self.assertEqual(self.state['title_library'][0],old)
        self.assertNotEqual(self.state['title_library'][1]['uuid'],'same')
        self.assertEqual(self.state['title_library'][1]['body'],'另一份新正文')

    def test_malformed_one_does_not_block_later_valid_delivery(self):
        self.queue('bad',[]);self.queue('good',self.row())
        self.assertEqual(self.receive(),1)
        with closing(sqlite3.connect(self.db)) as conn:
            states=dict(conn.execute('SELECT delivery_id,state FROM comic_article_inbox'))
            error=conn.execute("SELECT error FROM comic_article_inbox WHERE delivery_id='bad'").fetchone()[0]
        self.assertEqual(states,{'bad':'failed','good':'pushed'});self.assertTrue(error)

    def test_two_gui_instances_defer_pending_without_ack(self):
        self.queue('pending',self.row())
        with patch.object(bridge,'_can_receive',return_value=False):
            self.assertEqual(bridge.receive_pending(self.state,self.db),0)
        self.assertEqual(self.state['title_library'],[])
        with closing(sqlite3.connect(self.db)) as conn:
            self.assertEqual(conn.execute('SELECT state FROM comic_article_inbox').fetchone()[0],'pending')

    def test_busy_database_keeps_pending_and_retries_after_release(self):
        self.queue('busy',self.row())
        with closing(sqlite3.connect(self.db)) as writer:
            writer.execute('BEGIN IMMEDIATE')
            with self.assertRaises(sqlite3.OperationalError):self.receive()
            writer.rollback()
        self.assertEqual(self.state['title_library'],[])
        self.assertEqual(self.receive(),1)

    def test_failed_commit_rolls_back_receipt_database_and_memory(self):
        self.queue('commit',self.row())
        class Failing(sqlite3.Connection):
            def commit(self):raise sqlite3.OperationalError('simulated commit failure')
        original=sqlite3.connect
        with patch.object(bridge.sqlite3,'connect',side_effect=lambda *a,**kw:original(*a,**kw,factory=Failing)):
            with self.assertRaises(sqlite3.OperationalError):self.receive()
        self.assertEqual(self.state['title_library'],[])
        with closing(original(self.db)) as conn:
            self.assertEqual(conn.execute('SELECT state FROM comic_article_inbox').fetchone()[0],'pending')
            self.assertEqual(conn.execute("SELECT count(*) FROM app_collections WHERE namespace='title_library'").fetchone()[0],0)

    def test_idle_scheduler_does_not_repeat_process_probe_and_starts_once(self):
        class Root:
            def __init__(self):self.callbacks=[]
            def after(self,delay,callback):self.callbacks.append(callback)
        app=Mock(state=self.state,root=Root(),current_workspace='account_generation')
        with patch.object(bridge,'_can_receive') as probe:
            bridge.start_receiver(app,self.db);bridge.start_receiver(app,self.db)
            self.assertEqual(len(app.root.callbacks),1)
            for _ in range(2):
                app.root.callbacks.pop(0)();time.sleep(.04);app.root.callbacks.pop(0)()
            probe.assert_not_called()
        app.refresh_title_library_after_push.assert_not_called()
        self.assertEqual(self.state['wechat_accounts'],self.account_before)

    def test_push_callback_leaves_non_title_workspace_and_accounts_alone(self):
        app=pg.PicFactoryGUI.__new__(pg.PicFactoryGUI);app.state=self.state
        app.current_workspace='account_generation';app.refresh_all=Mock();app.root=Mock()
        app.refresh_title_library_after_push(['new'])
        app.refresh_all.assert_not_called();app.root.after_idle.assert_not_called()
        self.assertEqual(app.state['wechat_accounts'],self.account_before)


if __name__=='__main__':unittest.main()
