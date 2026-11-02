"""Receive local workbench deliveries; all in-memory merges run on Tk's thread."""
from contextlib import closing
import json
import os
from pathlib import Path
import queue
import sqlite3
import subprocess
import threading
import time
import uuid

VERSION = 'verified_push_bridge_v3_multi_reference'
INBOX_SQL = '''CREATE TABLE IF NOT EXISTS comic_article_inbox(
 delivery_id TEXT PRIMARY KEY,payload TEXT NOT NULL,state TEXT NOT NULL DEFAULT 'pending',
 target_key TEXT DEFAULT '',error TEXT DEFAULT '',created_at REAL NOT NULL,completed_at REAL)'''
RUNTIME_SQL = '''CREATE TABLE IF NOT EXISTS comic_bridge_runtime(
 pid INTEGER PRIMARY KEY,db_path TEXT,version TEXT,heartbeat REAL,phase TEXT)'''


def _can_receive(db_path):
    if os.name != 'nt':
        return True
    command = 'Get-CimInstance Win32_Process -Filter "Name=\'PicFactoryGUI.exe\'" | Select-Object ExecutablePath | ConvertTo-Json -Compress'
    check = subprocess.run(['powershell', '-NoProfile', '-Command', command], capture_output=True,
                           text=True, timeout=10, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    if check.returncode:
        return False
    processes = json.loads(check.stdout.strip() or '[]')
    if isinstance(processes, dict):
        processes = [processes]
    target = Path(db_path).resolve().parent
    count = 0
    for process in processes:
        executable = process.get('ExecutablePath')
        if not executable:
            continue
        runtime = Path(executable).resolve().parent
        candidate = runtime.parent.parent
        root = candidate if (candidate / 'picfactory_matrix.db').is_file() else runtime
        count += root == target
    return count <= 1


def _content_key(record):
    return tuple(str(record.get(k, '')).strip() for k in ('title', 'body', 'category'))


def receive_pending(state, db_path, *, process_checked=False):
    """Transactionally acknowledge deliveries and append to the existing list.

    An identical saved title keeps its current enabled/consumed state. UUID
    collisions allocate a new ID; malformed deliveries fail individually.
    """
    titles = state.setdefault('title_library', [])
    with closing(sqlite3.connect(db_path, timeout=0.05)) as conn:
        try:
            pending = conn.execute("SELECT 1 FROM comic_article_inbox WHERE state='pending' LIMIT 1").fetchone()
        except sqlite3.OperationalError as exc:
            if 'no such table' not in str(exc).lower():
                raise
            conn.execute(INBOX_SQL); conn.commit()
            return 0
        if not pending:
            return 0
        # Slow process discovery never holds a SQLite write transaction.
        if not process_checked and not _can_receive(db_path):
            return 0
        added = []
        conn.execute('BEGIN IMMEDIATE')
        try:
            rows = conn.execute("SELECT delivery_id,payload FROM comic_article_inbox WHERE state='pending' ORDER BY created_at,delivery_id LIMIT 500").fetchall()
            stored = {}
            keys = set()
            for key, raw in conn.execute("SELECT item_key,payload FROM app_collections WHERE namespace='title_library' ORDER BY sort_order,item_key"):
                keys.add(key)
                try:
                    value = json.loads(raw)
                except (ValueError, TypeError):
                    continue
                if isinstance(value, dict):
                    stored.setdefault(_content_key(value), (key, value))
            order = conn.execute("SELECT coalesce(max(sort_order),-1)+1 FROM app_collections WHERE namespace='title_library'").fetchone()[0]
            known = {str(v.get('uuid')) for v in titles if isinstance(v, dict)}
            count = 0
            for delivery, raw in rows:
                try:
                    value = json.loads(raw)
                    if not isinstance(value, dict) or not all(isinstance(value.get(k), str) and value[k].strip() for k in ('uuid', 'title', 'body', 'category')):
                        raise ValueError('缺少有效的UUID、标题、正文或分类')
                    content_key = _content_key(value)
                    match = stored.get(content_key)
                    if match:
                        key, value = match
                    else:
                        key = value['uuid']
                        if key in keys:
                            key = str(uuid.uuid4())
                            value = dict(value, uuid=key)
                            raw = json.dumps(value, ensure_ascii=False, separators=(',', ':'))
                        conn.execute("INSERT INTO app_collections(namespace,item_key,payload,sort_order,updated_at) VALUES('title_library',?,?,?,CURRENT_TIMESTAMP)", (key, raw, order))
                        keys.add(key); order += 1
                        stored[content_key] = (key, value)
                    identity = str(value.get('uuid'))
                    if identity not in known:
                        added.append(value); known.add(identity)
                    conn.execute("UPDATE comic_article_inbox SET state='pushed',target_key=?,error='',completed_at=? WHERE delivery_id=?", (key, time.time(), delivery))
                    count += 1
                except (ValueError, TypeError, KeyError) as exc:
                    conn.execute("UPDATE comic_article_inbox SET state='failed',error=?,completed_at=? WHERE delivery_id=?", (str(exc), time.time(), delivery))
            titles.extend(added)
            try:
                conn.commit()
            except BaseException:
                for value in added:
                    titles.remove(value)
                raise
            return count
        except BaseException:
            conn.rollback()
            raise


def sync_pushed_titles(state, db_path):
    """Merge offline/direct receipts before any whole-library save.

    Read the current saved row rather than the original receipt payload. A
    deleted title has no joined row and is never recreated from its receipt.
    """
    path = Path(db_path).resolve()
    if not path.is_file():
        return 0
    titles = state.setdefault('title_library', [])
    known = {str(row.get('uuid')) for row in titles if isinstance(row, dict)}
    added = []
    with closing(sqlite3.connect(path.as_uri()+'?mode=ro', uri=True, timeout=0.05)) as conn:
        try:
            keys = [row[0] for row in conn.execute("""SELECT DISTINCT c.item_key FROM comic_article_inbox i
                JOIN app_collections c ON c.namespace='title_library' AND c.item_key=i.target_key
                WHERE i.state='pushed' ORDER BY c.sort_order,c.item_key""") if row[0] not in known]
        except sqlite3.OperationalError as exc:
            if 'no such table' in str(exc).lower():
                return 0
            raise
        for start in range(0, len(keys), 500):
            batch = keys[start:start+500]
            placeholders = ','.join('?' for _ in batch)
            rows = conn.execute(f"SELECT payload FROM app_collections WHERE namespace='title_library' AND item_key IN ({placeholders}) ORDER BY sort_order,item_key", batch)
            for raw, in rows:
                value = json.loads(raw)
                if not isinstance(value, dict):
                    continue
                identity = str(value.get('uuid', '')).strip()
                if identity and identity not in known:
                    added.append(value); known.add(identity)
    titles.extend(added)
    return len(added)


def start_receiver(app, db_path):
    """Background DB/process probes; main-thread merges and local UI refreshes."""
    if getattr(app, '_title_receiver_started', False) is True:
        return
    app._title_receiver_started = True
    completed = queue.Queue(maxsize=1)
    busy = False
    last_revision = None

    def preflight(phase):
        allowed = False
        revision = None
        try:
            with closing(sqlite3.connect(db_path, timeout=0.05)) as conn:
                conn.execute(RUNTIME_SQL)
                conn.execute('INSERT OR REPLACE INTO comic_bridge_runtime VALUES(?,?,?,?,?)',
                             (os.getpid(), str(Path(db_path).resolve()), VERSION, time.time(), phase))
                conn.execute(INBOX_SQL); conn.commit()
                pending = conn.execute("SELECT 1 FROM comic_article_inbox WHERE state='pending' LIMIT 1").fetchone()
                revision = conn.execute("SELECT delivery_id,target_key,completed_at FROM comic_article_inbox WHERE state='pushed' ORDER BY delivery_id").fetchall()
            allowed = bool(pending) and _can_receive(db_path)
        except (sqlite3.Error, OSError, ValueError, subprocess.SubprocessError):
            pass
        finally:
            completed.put((allowed, revision))

    def poll():
        nonlocal busy, last_revision
        delay = 1000
        try:
            if not busy:
                busy = True
                phase = 'busy' if any(v for k, v in vars(app).items() if k.endswith('_running') and isinstance(v, bool)) else 'idle'
                threading.Thread(target=preflight, args=(phase,), daemon=True, name='title-inbox-preflight').start()
                delay = 80
            else:
                try:
                    allowed, revision = completed.get_nowait()
                except queue.Empty:
                    delay = 80
                    return
                busy = False
                if allowed or (revision is not None and revision != last_revision):
                    before = {str(row.get('uuid')) for row in app.state.get('title_library', []) if isinstance(row, dict)}
                    received = receive_pending(app.state, db_path, process_checked=True) if allowed else 0
                    synced = sync_pushed_titles(app.state, db_path)
                    last_revision = revision
                    if received or synced:
                        identities = [str(row.get('uuid')) for row in app.state.get('title_library', []) if isinstance(row, dict) and str(row.get('uuid')) not in before]
                        app.refresh_title_library_after_push(identities)
        except (sqlite3.Error, OSError, ValueError) as exc:
            app.last_title_receiver_error = str(exc)
        finally:
            try:
                app.root.after(delay, poll)
            except RuntimeError:
                pass
    app.root.after(500, poll)
