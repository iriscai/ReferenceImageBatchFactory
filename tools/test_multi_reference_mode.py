"""Exercise real routing, prompts and HTTP serialization without model calls."""
import copy
from pathlib import Path
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
from contextlib import closing
import json
import sqlite3
import time

import picfactory_gui as pg
from multi_reference_mode import GENERATION_MODE_MULTI_REFERENCE as MULTI


class Response:
    text = 'test-response'
    def __init__(self, status=200):
        self.status_code = status
    def json(self):
        return {'data': [{'b64_json': 'mock-image'}]}


class Client:
    def __init__(self, records, status=200):
        self.records, self.status, self.handles = records, status, []
    def post(self, endpoint, **kwargs):
        files = kwargs.get('files', [])
        if isinstance(files, dict):
            files = list(files.items())
        uploads = []
        for field, (name, handle, mime) in files:
            uploads.append((field, name, handle.read(), mime))
            self.handles.append(handle)
        self.records.append({'endpoint': endpoint, 'data': kwargs.get('data'),
                             'json': kwargs.get('json'), 'uploads': uploads})
        return Response(self.status)
    def close(self):
        pass


class MultiReferenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.background = self.root / 'background.png'
        self.character = self.root / 'character.png'
        self.background.write_bytes(b'original-background')
        self.character.write_bytes(b'original-character')
        self.refs = [
            {'name': '背景', 'image_path': str(self.background), 'width': 32, 'height': 48, 'enabled': True},
            {'name': '形象', 'image_path': str(self.character), 'width': 96, 'height': 96, 'enabled': True},
        ]
        self.account = {'uuid': 'a', 'account_id': 'a', 'name': 'chat_测试', 'generation_mode': MULTI,
                        'title_category': '国际', 'grid': '单幅', 'comment_enabled': '否',
                        'multi_reference_config': {'background_names': ['背景'], 'character_names': ['形象']}}
        self.app = pg.PicFactoryGUI.__new__(pg.PicFactoryGUI)
        self.app.state = {'reference_images': self.refs, 'fixed_style_templates': [{'name': '画风', 'content': 'fixed-style', 'full_prompt': 'fixed-style'}], 'title_library': [], 'generated_works': []}
        self.app.image_batch_stop_requested = False
        self.app.account_generation_stop_requested = False
        self.app.image_batch_active_clients = set()
        self.app.image_batch_active_clients_lock = threading.Lock()
        self.app.account_generation_log = Mock()
        self.app.image_batch_log = Mock()
        self.app.wait_with_stop = lambda *_: False
        self.app.next_text_api_key_start = lambda *_: 0
        self.app.next_image_api_key_start = lambda *_: 0
        self.app.save_image_payload = lambda *args, **kwargs: Path(kwargs['save_path']).write_bytes(b'generated-test-image')
        self.app.normalize_generated_image = lambda *_: {'message': 'test'}
        self.app.compress_image_under_size = lambda *_: None
        self.api = {'endpoint': 'https://unit.invalid/v1/images/generations', 'model': 'unit-model', 'keys': ['unit-key']}

    def test_binding_roles_size_and_original_paths(self):
        binding = self.app.account_generation_binding(self.account)
        self.assertEqual(binding['mode'], 'multi_reference')
        self.assertEqual(binding['image_paths'], [str(self.background.resolve()), str(self.character.resolve())])
        self.assertEqual([r['role'] for r in binding['reference_roles']], ['background', 'character'])
        self.assertEqual(self.app.reference_image_request_size(binding, '768x1024'), '32x48')

    def test_missing_disabled_and_duplicate_refs_fail_before_request(self):
        for failure in ['missing', 'disabled', 'duplicate']:
            with self.subTest(failure=failure):
                account = copy.deepcopy(self.account)
                refs = copy.deepcopy(self.refs)
                if failure == 'missing':
                    account['multi_reference_config']['character_names'] = ['不存在']
                elif failure == 'disabled':
                    refs[1]['enabled'] = False
                else:
                    account['multi_reference_config']['character_names'] = ['背景']
                self.app.state['reference_images'] = refs
                with self.assertRaises(RuntimeError):
                    self.app.account_generation_binding(account)

    def test_old_five_modes_ignore_multi_reference_and_persona_settings(self):
        for mode in [pg.GENERATION_MODE_REFERENCE, pg.GENERATION_MODE_STYLE, pg.GENERATION_MODE_13,
                     pg.GENERATION_MODE_REFERENCE_SEQUENCE, pg.GENERATION_MODE_GRID_STYLE]:
            with self.subTest(mode=mode):
                account = {'name': 'old', 'generation_mode': mode, 'reference_name': '背景', 'style_name': '画风'}
                before = self.app.account_generation_binding(account)
                account.update({'multi_reference_config': {'background_names': ['不存在'], 'character_names': ['不存在']},
                                'persona_reference_names': ['同样不存在']})
                self.assertEqual(self.app.account_generation_binding(account), before)

    def test_new_prompt_has_explicit_roles_text_and_setting_sheet_exclusion(self):
        binding = self.app.account_generation_binding(self.account)
        prompt = self.app.build_multi_reference_frame_prompt(1, 2, '标题', '完整原文。', '人物点头',
                    binding['names'], '32x48', reference_roles=binding['reference_roles'])
        for text in ['第1张：背景；用途：背景与画风', '第2张：形象；用途：人物形象',
                     '完整原文。', '不复制设定图的白底', '最高依据']:
            self.assertIn(text, prompt)

    def test_real_multipart_uploads_all_originals_in_order_and_closes_handles(self):
        records = []
        client = Client(records)
        self.app.call_multi_reference_image_generation(None, self.api, 'prompt', str(self.root/'out.png'), '32x48', 1,
            client=client, reference_image_path=str(self.background), extra_reference_paths=[str(self.character)])
        self.assertTrue(records[0]['endpoint'].endswith('/images/edits'))
        self.assertEqual([(x[0], x[2]) for x in records[0]['uploads']], [('image', b'original-background'), ('image', b'original-character')])
        self.assertTrue(all(h.closed for h in client.handles))

    def test_http_error_never_falls_back_to_fewer_reference_images(self):
        records = []
        with self.assertRaises(RuntimeError):
            self.app.call_multi_reference_image_generation(None, self.api, 'prompt', str(self.root/'out.png'), '32x48', 1,
                client=Client(records, 400), reference_image_path=str(self.background), extra_reference_paths=[str(self.character)])
        self.assertEqual(len(records), 3)
        self.assertTrue(all(len(r['uploads']) == 2 for r in records))

    def test_no_reference_or_cancelled_request_never_calls_http(self):
        client = Client([])
        with self.assertRaises(RuntimeError):
            self.app.call_multi_reference_image_generation(None, self.api, 'prompt', str(self.root/'out.png'), '32x48', 1, client=client)
        stop = threading.Event(); stop.set()
        with self.assertRaises(RuntimeError):
            self.app.call_multi_reference_image_generation(None, self.api, 'prompt', str(self.root/'out.png'), '32x48', 1,
                client=client, reference_image_path=str(self.background), extra_reference_paths=[str(self.character)], stop_event=stop)
        self.assertEqual(client.records, [])

    def test_old_transport_keeps_one_reference_and_style_keeps_json(self):
        for reference in [None, str(self.background)]:
            records = []
            self.app.call_image_generation(None, self.api, 'unchanged', str(self.root/'old.png'), '32x48', 1,
                client=Client(records), reference_image_path=reference)
            self.assertEqual(len(records[0]['uploads']), 1 if reference else 0)
            self.assertEqual(records[0]['json'], None if reference else {'model': 'unit-model', 'prompt': 'unchanged', 'size': '32x48'})

    def test_execute_new_title_uses_dedicated_transport_for_every_frame(self):
        records = []
        httpx = SimpleNamespace(Client=lambda **_: Client(records), Timeout=lambda *_, **__: None)
        body = '第一句描述主角在桌边认真查看材料。第二句描述主角抬头解释事情经过。'
        self.app.call_account_generation_text = lambda *_args, **_kwargs: '无副角色'
        self.app.close_account_generation_text_context = lambda *_: None
        self.app.account_generation_work_paths = lambda *_: (self.root/'作品', '文章.txt')
        saved = []
        self.app.persist_generated_work = lambda record: saved.append(copy.deepcopy(record))
        self.app.call_image_generation = Mock(side_effect=AssertionError('Old image chain must not run'))
        config = {'output_root': str(self.root), 'group_retry_count': 0, 'max_workers': 2}
        work = self.app.execute_account_generation_title(httpx, {'keys': ['unit-text']}, self.api, self.account,
                    {'title': '测试', 'body': body, 'category': '国际'}, config, None, {},
                    self.app.account_generation_binding(self.account), threading.Event())
        self.assertEqual(work['status'], '成功', work.get('error'))
        self.assertEqual(work['generation_mode'], MULTI)
        self.assertEqual(''.join(s['copy'] for s in work['scenes']), body)
        self.assertEqual((self.root/'作品'/'文章.txt').read_text(encoding='utf-8'), body)
        self.assertGreater(len(records), 1)
        self.assertTrue(all(len(r['uploads']) == 2 for r in records))
        self.assertTrue(all([f[2] for f in r['uploads']] == [b'original-background', b'original-character'] for r in records))
        self.app.call_image_generation.assert_not_called()

    def test_worker_schedules_multi_reference_without_article_template(self):
        self.app.state['title_library'] = [{'title': '测试标题', 'body': '测试原文', 'category': '国际', 'status': '启用'}]
        self.app.load_storyboard_runtime = lambda: (None, None)
        self.app.account_generation_stop_event = threading.Event()
        self.app.load_account_generation_api_config = lambda *_args, **_kwargs: ({}, {})
        self.app.account_generation_run_output_root = lambda *_: self.root
        scheduled = []
        self.app.run_account_generation_tasks = lambda *args: scheduled.extend(args[3])
        self.app.set_account_generation_running_buttons = lambda *_: None
        self.app.set_account_generation_summary = Mock()
        self.app.root = SimpleNamespace(after=lambda *_: None)
        self.app.account_generation_worker([self.account], {'title_count': 1, 'output_root': str(self.root)})
        self.assertEqual(len(scheduled), 1, self.app.account_generation_log.call_args_list)
        self.assertEqual(scheduled[0][2]['generation_mode'], MULTI)
        self.assertEqual(scheduled[0][4]['mode'], 'multi_reference')


class MultiReferenceUITests(unittest.TestCase):
    def setUp(self):
        from test_ui_responsiveness import AccountCanvasTests
        AccountCanvasTests.setUp(self)
        folder = Path(self.temp.name)
        for name in ['背景', '形象']:
            (folder / (name+'.png')).write_bytes(b'unit-image')
        self.app.state['reference_images'] = [{'name': n, 'image_path': str(folder/(n+'.png')), 'enabled': True} for n in ['背景','形象']]
        self.old = {'uuid': 'old', 'name': '原账号', 'account_id': 'old', 'generation_mode': pg.GENERATION_MODE_13, 'reference_name': '背景', 'enabled': True}
        self.new = {'uuid': 'new', 'name': 'chat_测试', 'account_id': 'new', 'generation_mode': MULTI, 'enabled': True,
                    'reference_name': '原字段保留', 'multi_reference_config': {'background_names': ['背景'], 'character_names': ['形象']}}
        self.app.state['wechat_accounts'] = [self.old, self.new]
        pg.save_db_collection('wechat_accounts', self.app.state['wechat_accounts'])
        self.app.account_generation_running = False
        self.app.open_multi_reference_config()
        self.dialog = next(w for w in self.app.root.winfo_children() if isinstance(w, pg.tk.Toplevel))
        self.app.root.update()

    def tearDown(self):
        from test_ui_responsiveness import AccountCanvasTests
        for child in self.app.root.winfo_children():
            if isinstance(child, pg.tk.Toplevel):
                child.destroy()
        AccountCanvasTests.tearDown(self)

    def widgets(self, root):
        for child in root.winfo_children():
            yield child
            yield from self.widgets(child)

    def test_cancel_keeps_every_account_record_untouched(self):
        with closing(sqlite3.connect(pg.MATRIX_DB_PATH)) as conn:
            before = conn.execute("SELECT item_key,payload FROM app_collections WHERE namespace='wechat_accounts' ORDER BY item_key").fetchall()
        self.dialog.destroy()
        with closing(sqlite3.connect(pg.MATRIX_DB_PATH)) as conn:
            after = conn.execute("SELECT item_key,payload FROM app_collections WHERE namespace='wechat_accounts' ORDER BY item_key").fetchall()
        self.assertEqual(before, after)

    def test_hidden_search_selection_survives_save_and_other_account_is_unchanged(self):
        before_old = copy.deepcopy(self.old)
        entries = [w for w in self.widgets(self.dialog) if isinstance(w, pg.ttk.Entry) and not isinstance(w, pg.ttk.Combobox)]
        entries[0].insert(0, '没有匹配项')
        time.sleep(0.17)
        self.app.root.update()
        trees = [w for w in self.widgets(self.dialog) if isinstance(w, pg.ttk.Treeview)]
        self.assertEqual(trees[0].get_children(), ())
        button = next(w for w in self.widgets(self.dialog) if isinstance(w, pg.ttk.Button) and w.cget('text') == '保存此账号')
        with patch.object(pg.messagebox, 'showerror', side_effect=AssertionError('Unexpected save error')):
            button.invoke()
        self.assertEqual(self.old, before_old)
        self.assertEqual(self.new['reference_name'], '原字段保留')
        self.assertEqual(self.new['multi_reference_config']['background_names'], ['背景'])
        self.assertEqual(self.new['multi_reference_config']['character_names'], ['形象'])
        with closing(sqlite3.connect(pg.MATRIX_DB_PATH)) as conn:
            stored = {k:json.loads(v) for k,v in conn.execute("SELECT item_key,payload FROM app_collections WHERE namespace='wechat_accounts'")}
        self.assertEqual(stored['old'], before_old)
        self.assertEqual(stored['new']['multi_reference_config'], self.new['multi_reference_config'])


if __name__ == '__main__':
    unittest.main()
