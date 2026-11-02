"""Direct workbench pushes must reach the live list, not just SQLite."""
from contextlib import closing
import json
from pathlib import Path
import sqlite3
import tempfile
import time
import unittest
from unittest.mock import Mock,patch

import picfactory_gui as pg
import title_library_bridge as bridge


class TitlePushRefreshTests(unittest.TestCase):
    def setUp(self):
        storage=tempfile.TemporaryDirectory();self.addCleanup(storage.cleanup)
        folder=Path(storage.name)
        context=patch.multiple(pg,APP_DIR=folder,MATRIX_DB_PATH=folder/'db.sqlite',STATE_PATH=folder/'state.json',
                               PACKAGED_MATRIX_DB_PATH=folder/'none.db',_MATRIX_DB_READY=False,_DB_COLLECTION_DIGESTS={})
        context.start();self.addCleanup(context.stop)
        pg.ensure_matrix_db()
        with closing(sqlite3.connect(pg.MATRIX_DB_PATH)) as c,c:c.execute(bridge.INBOX_SQL)
        warnings=patch.object(pg.messagebox,'showwarning');warnings.start();self.addCleanup(warnings.stop)
        self.old=[self.row('old'+str(n),'筛选词旧标题'+str(n)) for n in range(40)]
        pg.save_db_collection('title_library',self.old)
        self.state={'title_library':list(self.old),'generated_works':[],'users':[]}

    def row(self,identity,title):
        return {'uuid':identity,'title':title,'body':'完整正文：'+title,'category':'财经','status':'启用',
                'used':False,'used_at':'','note':'','updated_at':'2026-10-31 16:00:00'}

    def direct_push(self,identity='pushed',consumed=False):
        original=self.row(identity,'筛选词新推送标题')
        current=dict(original)
        if consumed:current.update(status='停用',used=True,used_at='2026-10-31 16:01:00')
        with closing(sqlite3.connect(pg.MATRIX_DB_PATH)) as c,c:
            c.execute("INSERT INTO app_collections(namespace,item_key,payload,sort_order) VALUES('title_library',?,?,40)",(identity,json.dumps(current)))
            c.execute("INSERT INTO comic_article_inbox(delivery_id,payload,state,target_key,created_at,completed_at) VALUES(?,?,'pushed',?,1,2)",(identity,json.dumps(original),identity))
        return current

    def test_direct_push_syncs_in_place_once_using_current_consumption_state(self):
        expected=self.direct_push(consumed=True);original_list=self.state['title_library']
        self.assertEqual(bridge.sync_pushed_titles(self.state,pg.MATRIX_DB_PATH),1)
        self.assertIs(self.state['title_library'],original_list)
        self.assertEqual(original_list[-1],expected)
        self.assertEqual(bridge.sync_pushed_titles(self.state,pg.MATRIX_DB_PATH),0)

    def test_stale_receipt_does_not_resurrect_a_deleted_title(self):
        self.direct_push()
        with closing(sqlite3.connect(pg.MATRIX_DB_PATH)) as c,c:
            c.execute("DELETE FROM app_collections WHERE namespace='title_library' AND item_key='pushed'")
        self.assertEqual(bridge.sync_pushed_titles(self.state,pg.MATRIX_DB_PATH),0)
        self.assertEqual(len(self.state['title_library']),40)

    def test_settings_save_between_timer_ticks_keeps_the_direct_push(self):
        expected=self.direct_push(consumed=True)
        app=pg.PicFactoryGUI.__new__(pg.PicFactoryGUI)
        app.state=self.state;app.current_workspace='writing'
        app.flush_loaded_identity_options=Mock();app.write_state_file=Mock()
        app.save_state()
        with closing(sqlite3.connect(pg.MATRIX_DB_PATH)) as c:
            row=json.loads(c.execute("SELECT payload FROM app_collections WHERE namespace='title_library' AND item_key='pushed'").fetchone()[0])
        self.assertEqual(row,expected)

    def test_background_poll_refreshes_an_already_pushed_row_without_pending_work(self):
        expected=self.direct_push()
        class Root:
            def __init__(self):self.callbacks=[]
            def after(self,delay,callback):self.callbacks.append(callback)
        app=Mock(state=self.state,current_workspace='title_library',root=Root())
        with patch.object(bridge,'_can_receive') as check:
            bridge.start_receiver(app,pg.MATRIX_DB_PATH)
            deadline=time.perf_counter()+2
            while not app.refresh_title_library_after_push.called and time.perf_counter()<deadline:
                app.root.callbacks.pop(0)();time.sleep(.005)
            check.assert_not_called()
        app.refresh_title_library_after_push.assert_called_once_with(['pushed'])
        self.assertEqual(self.state['title_library'][-1],expected)

    def make_ui(self):
        root=pg.tk.Tk();root.withdraw();self.addCleanup(root.destroy)
        app=pg.PicFactoryGUI.__new__(pg.PicFactoryGUI)
        app.root=root;app.main=pg.ttk.Frame(root);app.main.pack();app.state=self.state
        app.current_workspace='title_library';app.save_state=Mock()
        app.render_title_library_workspace();root.update_idletasks()
        return app

    def widgets(self,parent):
        for child in parent.winfo_children():
            yield child
            yield from self.widgets(child)

    def test_live_table_refresh_keeps_filters_updates_summary_and_selects_new_page(self):
        app=self.make_ui()
        search=next(w for w in self.widgets(app.main) if w.winfo_class()=='TEntry')
        search.insert(0,'筛选词')
        table=app._title_library_table_widget;summary=app._title_library_summary_frame
        self.direct_push()
        bridge.sync_pushed_titles(self.state,pg.MATRIX_DB_PATH)
        app.refresh_title_library_after_push(['pushed'])
        self.assertIs(app._title_library_table_widget,table)
        self.assertIs(app._title_library_summary_frame,summary)
        self.assertEqual(search.get(),'筛选词')
        self.assertIn('pushed',table.get_children())
        self.assertEqual(table.selection(),('pushed',))
        self.assertIn('41',[str(w.cget('text')) for w in self.widgets(summary) if w.winfo_class()=='Label'])

    def test_manual_refresh_also_reads_external_titles_and_updates_remaining_count(self):
        app=self.make_ui();self.direct_push()
        app._title_library_refresh_callback()
        self.assertEqual(len(self.state['title_library']),41)
        summary=app._title_library_summary_frame
        self.assertIn('41',[str(w.cget('text')) for w in self.widgets(summary) if w.winfo_class()=='Label'])

    def test_push_during_page_construction_defers_rebuild_to_avoid_reentry(self):
        app=pg.PicFactoryGUI.__new__(pg.PicFactoryGUI)
        app.current_workspace='title_library';app.root=Mock();app.refresh_all=Mock()
        app.refresh_title_library_after_push(['pushed'])
        app.refresh_all.assert_not_called()
        app.root.after_idle.assert_called_once_with(app.refresh_all)


if __name__=='__main__':unittest.main()
