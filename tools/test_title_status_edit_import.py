"""Status edits/imports must survive persistence, history sync and a new success."""
from contextlib import closing
import copy
import json
from pathlib import Path
import sqlite3
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch
import picfactory_gui as pg


class TitleStatusEditImportTests(unittest.TestCase):
    def setUp(self):
        storage = tempfile.TemporaryDirectory()
        self.addCleanup(storage.cleanup)
        self.folder = Path(storage.name)
        context = patch.multiple(pg, APP_DIR=self.folder, MATRIX_DB_PATH=self.folder/'db.sqlite',
                                 STATE_PATH=self.folder/'state.json', PACKAGED_MATRIX_DB_PATH=self.folder/'none.db',
                                 _MATRIX_DB_READY=False, _DB_COLLECTION_DIGESTS={})
        context.start()
        self.addCleanup(context.stop)
        pg.ensure_matrix_db()
        self.row = dict(uuid='one', title='需要重试的标题', body='完整正文', category='国际', status='停用',
                        used=True, used_at='2026-11-03 18:00:00', note='', updated_at='2026-11-03 18:00:00')
        self.success = dict(uuid='old-work', title=self.row['title'], account_id='account', status='成功',
                            updated_at='2026-11-03 18:00:00')
        self.state = {'title_library':[self.row], 'generated_works':[self.success], 'users':[]}
        pg.save_db_collection('title_library', self.state['title_library'])
        pg.save_db_collection('generated_works', self.state['generated_works'])
        self.root = pg.tk.Tk()
        self.root.geometry('1300x900+5000+5000')
        self.errors = []
        self.root.report_callback_exception = lambda typ, exc, tb: self.errors.append(exc)
        self.addCleanup(self.close_root)
        self.app = pg.PicFactoryGUI.__new__(pg.PicFactoryGUI)
        self.app.root = self.root
        self.app.main = pg.ttk.Frame(self.root)
        self.app.main.pack(fill='both', expand=True)
        self.app.state = self.state
        self.app.current_workspace = 'title_library'
        self.app.account_generation_state_lock = threading.RLock()
        self.app.flush_loaded_identity_options = Mock()
        self.app.prepare_undo = Mock()
        self.app.render_title_library_workspace()
        self.root.update()

    def close_root(self):
        for token in self.root.tk.call('after', 'info'):
            self.root.after_cancel(token)
        self.root.destroy()

    def widgets(self, parent):
        for child in parent.winfo_children():
            yield child
            yield from self.widgets(child)

    def button(self, parent, text):
        return next(w for w in self.widgets(parent) if isinstance(w, pg.ttk.Button) and w.cget('text') == text)

    def stored(self, identity='one'):
        with closing(sqlite3.connect(pg.MATRIX_DB_PATH)) as db:
            return json.loads(db.execute("SELECT payload FROM app_collections WHERE namespace='title_library' AND item_key=?", (identity,)).fetchone()[0])

    def import_sheet(self, headers, rows, accept=True):
        path = self.folder/'titles.xlsx'
        pg.build_xlsx(path, [('标题库', [headers, *rows])])
        with patch.object(pg.filedialog, 'askopenfilename', return_value=str(path)), \
             patch.object(pg.messagebox, 'askyesno', return_value=accept), \
             patch.object(pg.messagebox, 'showinfo'), patch.object(pg.messagebox, 'showerror') as error:
            self.button(self.app.main, '导入Excel').invoke()
            self.root.update()
            error.assert_not_called()
        self.assertEqual(self.errors, [])

    def test_editor_can_reenable_a_consumed_title_and_disable_it_again(self):
        status_filter = next(w for w in self.widgets(self.app.main) if isinstance(w, pg.ttk.Combobox) and '全部状态' in w.cget('values'))
        status_filter.set('全部状态')
        self.root.update()
        tree = self.app._title_library_table_widget
        tree.xview_moveto(1)
        self.root.update_idletasks()
        x, y, width, height = tree.bbox('one', tree['columns'][-1])
        tree.event_generate('<Button-1>', x=x+12, y=y+height//2)
        tree.event_generate('<ButtonRelease-1>', x=x+12, y=y+height//2)
        self.root.update()
        dialog = next(w for w in self.root.winfo_children() if isinstance(w, pg.tk.Toplevel))
        status = next(w for w in self.widgets(dialog) if isinstance(w, pg.ttk.Combobox) and tuple(w.cget('values')) == ('启用', '停用'))
        status.set('启用')
        self.button(dialog, '保存').invoke()
        self.root.update()
        self.assertEqual(self.errors, [])
        self.assertEqual(self.stored()['status'], '启用')
        self.assertFalse(self.stored()['used'])
        self.assertEqual(tree.set('one', 'status'), '启用')
        self.assertEqual(len(self.app.account_generation_title_records({'title_category':'国际'})), 1)
        tree.xview_moveto(1)
        self.root.update_idletasks()
        x, y, width, height = tree.bbox('one', tree['columns'][-1])
        tree.event_generate('<Button-1>', x=x+12, y=y+height//2)
        tree.event_generate('<ButtonRelease-1>', x=x+12, y=y+height//2)
        self.root.update()
        dialog = next(w for w in self.root.winfo_children() if isinstance(w, pg.tk.Toplevel))
        status = next(w for w in self.widgets(dialog) if isinstance(w, pg.ttk.Combobox) and tuple(w.cget('values')) == ('启用', '停用'))
        status.set('停用')
        self.button(dialog, '保存').invoke()
        self.root.update()
        self.assertEqual(self.errors, [])
        self.assertEqual(self.stored()['status'], '停用')
        self.assertFalse(self.stored()['used'])
        self.assertEqual(self.app.account_generation_title_records({'title_category':'国际'}), [])

    def test_excel_explicit_enable_refreshes_ui_database_and_available_count(self):
        original_list = self.state['title_library']
        self.import_sheet(['UUID','标题','状态'], [['one',self.row['title'],'启用']])
        self.assertIs(self.state['title_library'], original_list)
        self.assertEqual(self.stored()['status'], '启用')
        self.assertFalse(self.stored()['used'])
        self.assertEqual(self.app._title_library_table_widget.set('one', 'status'), '启用')
        self.assertEqual(self.app.title_library_remaining_counts()['国际'], 1)
        self.assertEqual(len(self.app.account_generation_title_records({'title_category':'国际'})), 1)

    def test_excel_missing_or_blank_status_does_not_reset_consumption(self):
        for headers, row in [(['UUID','标题'], ['one',self.row['title']]),
                             (['UUID','标题','状态'], ['one',self.row['title'],''])]:
            with self.subTest(headers=headers):
                self.import_sheet(headers, [row])
                self.assertEqual(self.stored()['status'], '停用')
                self.assertTrue(self.stored()['used'])

    def test_cancelled_import_leaves_state_and_database_untouched(self):
        before = copy.deepcopy(self.state)
        stored = self.stored()
        self.import_sheet(['UUID','标题','状态'], [['one',self.row['title'],'启用']], accept=False)
        self.assertEqual(self.state, before)
        self.assertEqual(self.stored(), stored)

    def test_unrelated_save_keeps_success_history_backfill(self):
        self.row.update(status='启用', used=False, used_at='')
        self.app.save_state()
        self.assertEqual(self.stored()['status'], '停用')
        self.assertTrue(self.stored()['used'])

    def test_explicit_reactivation_survives_save_and_restart(self):
        self.row['status'] = '启用'
        pg.reactivate_title_records(self.state, ['one'])
        self.app.save_state()
        fresh = {'title_library':pg.load_db_collection('title_library'), 'generated_works':pg.load_db_collection('generated_works')}
        for _ in range(3):
            pg.normalize_title_consumption(fresh)
        self.assertEqual(fresh['title_library'][0]['status'], '启用')
        self.assertFalse(fresh['title_library'][0]['used'])

    def test_new_success_consumes_reactivated_title_even_with_same_timestamp(self):
        self.row['status'] = '启用'
        pg.reactivate_title_records(self.state, ['one'])
        self.app.persist_generated_work(dict(self.success, uuid='new-work'))
        pg.normalize_title_consumption(self.state)
        self.assertEqual(self.stored()['status'], '停用')
        self.assertTrue(self.stored()['used'])
        self.assertEqual(self.app.account_generation_title_records({'title_category':'国际'}), [])

    def test_duplicate_rows_cannot_undo_reset_or_be_silently_enabled(self):
        duplicate = dict(self.row, uuid='two', category='军事')
        self.state['title_library'].append(duplicate)
        self.row['status'] = '启用'
        pg.reactivate_title_records(self.state, ['one'])
        pg.normalize_title_consumption(self.state)
        self.assertFalse(self.row['used'])
        self.assertFalse(duplicate['used'])
        self.assertEqual(duplicate['status'], '停用')
        self.app.persist_generated_work(dict(self.success, uuid='new-work'))
        self.assertTrue(all(r['used'] and r['status']=='停用' for r in self.state['title_library']))

    def test_new_failure_after_reactivation_remains_retryable(self):
        self.row['status'] = '启用'
        pg.reactivate_title_records(self.state, ['one'])
        failure = dict(self.success, uuid='new-failure', status='失败', updated_at='2026-11-03 18:01:00')
        self.app.persist_generated_work(failure)
        result = self.app.account_generation_failed_records([{'account_id':'account'}])
        self.assertEqual([r['uuid'] for r in result], ['new-failure'])
        self.assertEqual(self.row['status'], '启用')

    def test_import_new_row_appears_in_open_list_and_summary(self):
        self.import_sheet(['UUID','标题','正文','分类','状态'], [['new','新标题','新正文','军事','启用']])
        tree = self.app._title_library_table_widget
        self.assertIn('new', tree.get_children())
        self.assertEqual(tree.set('new', 'title'), '新标题')
        self.assertEqual(self.app.title_library_remaining_counts()['军事'], 1)
        self.assertEqual(self.stored('new')['body'], '新正文')


if __name__ == '__main__':
    unittest.main()
