"""Checkbox selection used exclusively by the multi-reference image mode."""
import copy
import tkinter as tk
from tkinter import ttk, messagebox

MODE_MULTI = '多参考图生图'


class ReferenceChecklist(ttk.Frame):
    def __init__(self, parent, names, selected=()):
        super().__init__(parent)
        self.names = list(dict.fromkeys(names))
        self.checked = list(dict.fromkeys(selected))
        self.visible = {}
        self.timer = None
        self.search = tk.StringVar()
        ttk.Entry(self, textvariable=self.search).pack(fill='x', pady=(0, 6))
        row = ttk.Frame(self); row.pack(fill='both', expand=True)
        self.tree = ttk.Treeview(row, show='tree', selectmode='none')
        scroll = ttk.Scrollbar(row, orient='vertical', command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll.set)
        scroll.pack(side='right', fill='y'); self.tree.pack(side='left', fill='both', expand=True)
        self.count = tk.StringVar()
        footer = ttk.Frame(self); footer.pack(fill='x', pady=(6, 0))
        ttk.Label(footer, textvariable=self.count).pack(side='left')
        ttk.Button(footer, text='清空本栏', command=lambda: self.set_names([])).pack(side='right')
        self.summary = tk.StringVar()
        ttk.Label(self, textvariable=self.summary, wraplength=440).pack(fill='x', pady=(4, 0))
        self.tree.bind('<Button-1>', self.on_click)
        self.tree.bind('<space>', self.on_space)
        self.bind('<Destroy>', self.on_destroy, add='+')
        self.search.trace_add('write', self.queue_refresh)
        self.refresh()

    def get_names(self):
        return list(self.checked)

    def set_names(self, names):
        self.checked = list(dict.fromkeys(names))
        self.refresh()

    def queue_refresh(self, *_):
        if self.timer is not None:
            self.after_cancel(self.timer)
        self.timer = self.after(150, self.refresh)

    def refresh(self):
        if not self.winfo_exists():
            return
        if self.timer is not None:
            self.after_cancel(self.timer)
        self.timer = None
        keyword = self.search.get().strip().lower()
        visible = [n for n in self.names if keyword in n.lower()]
        self.tree.delete(*self.tree.get_children())
        self.visible = {str(i): n for i, n in enumerate(visible)}
        checked = set(self.checked)
        for item, name in self.visible.items():
            self.tree.insert('', 'end', iid=item, text=('☑ ' if name in checked else '□ ')+name)
        self.update_summary()

    def update_summary(self):
        self.count.set(f'已选 {len(self.checked)} 张')
        names = '、'.join(self.checked)
        self.summary.set(('已选：'+names[:240]+('…' if len(names)>240 else '')) if names else '尚未勾选参考图')

    def toggle_item(self, item):
        name = self.visible.get(item)
        if name is None:
            return
        if name in self.checked:
            self.checked.remove(name)
        else:
            self.checked.append(name)
        self.tree.item(item, text=('☑ ' if name in self.checked else '□ ')+name)
        self.update_summary()

    def on_click(self, event):
        item = self.tree.identify_row(event.y)
        if item:
            self.tree.focus(item)
            self.tree.focus_set()
            self.toggle_item(item)
            return 'break'

    def on_space(self, _event):
        self.toggle_item(self.tree.focus())
        return 'break'

    def on_destroy(self, event):
        if event.widget is self and self.timer is not None:
            self.after_cancel(self.timer)
            self.timer = None


class MultiReferencePickerMixin:
    def _multi_reference_picker_body(self, parent, config):
        ttk.Label(parent, text='逐张点击方框即可多选，无需 Ctrl/Shift。搜索后已勾选的图片会保留。').pack(anchor='w')
        columns = ttk.Frame(parent); columns.pack(fill='both', expand=True, pady=10)
        columns.columnconfigure(0, weight=1); columns.columnconfigure(1, weight=1); columns.rowconfigure(0, weight=1)
        names = sorted({str(r.get('name', '')).strip() for r in self.state.get('reference_images', [])
                        if isinstance(r, dict) and str(r.get('name', '')).strip() and r.get('enabled', True) is not False})
        editors = {}
        for column, (key, title) in enumerate([('background_names','背景与画风参考图'), ('character_names','人物形象参考图')]):
            box = ttk.LabelFrame(columns, text=title, padding=8)
            box.grid(row=0, column=column, sticky='nsew', padx=(0,8) if column==0 else (8,0))
            check = ReferenceChecklist(box, names, self.normalize_multi_reference_names(config.get(key)))
            check.pack(fill='both', expand=True); editors[key] = check
        size = tk.StringVar(value=str(config.get('image_size') or ''))
        row = ttk.Frame(parent); row.pack(fill='x')
        ttk.Label(row, text='本账号尺寸（留空跟随首张背景图）：').pack(side='left')
        ttk.Entry(row, textvariable=size, width=20).pack(side='left', padx=6)
        return editors, size

    def _multi_reference_config_from_picker(self, original, editors, size):
        result = dict(original or {})
        result.update({key: picker.get_names() for key, picker in editors.items()})
        result.update(version=1, image_size=size.get().strip())
        return result

    def open_multi_reference_accounts_window(self):
        if getattr(self, 'account_generation_running', False):
            messagebox.showinfo('提示','请等待当前生图任务结束后再修改多参考图配置。',parent=self.root)
            return
        accounts = [a for a in self.state.get('wechat_accounts',[]) if isinstance(a,dict)]
        if not accounts:
            return
        dialog = tk.Toplevel(self.root); dialog.title('多参考图配置'); dialog.geometry('1120x760')
        dialog.minsize(820,560); dialog.transient(self.root); dialog.grab_set()
        body = ttk.Frame(dialog,padding=14); body.pack(fill='both',expand=True)
        ttk.Label(body,text='账号（保存后将此账号切换为多参考图生图）').pack(anchor='w')
        combo = ttk.Combobox(body,state='readonly',values=[f"{a.get('name','')}  [{a.get('account_id','')}]" for a in accounts])
        combo.pack(fill='x',pady=(4,10))
        editors,size = self._multi_reference_picker_body(body,{})
        def load(_event=None):
            if combo.current()<0:return
            config = accounts[combo.current()].get('multi_reference_config') or {}
            for key,picker in editors.items():
                picker.search.set(''); picker.set_names(self.normalize_multi_reference_names(config.get(key)))
            size.set(str(config.get('image_size') or ''))
        def save():
            if combo.current()<0:return
            account = accounts[combo.current()]; updated = copy.deepcopy(account)
            updated['generation_mode'] = MODE_MULTI
            updated['multi_reference_config'] = self._multi_reference_config_from_picker(account.get('multi_reference_config'),editors,size)
            updated['updated_at'] = self.record_updated_at()
            try:
                self.multi_reference_binding(updated); self.multi_reference_save_account(updated)
            except Exception as exc:
                messagebox.showerror('配置未保存',str(exc),parent=dialog); return
            account.clear(); account.update(updated); dialog.destroy(); self.refresh_all()
        actions = ttk.Frame(body); actions.pack(fill='x',pady=(14,0))
        ttk.Button(actions,text='保存此账号',command=save).pack(side='right')
        ttk.Button(actions,text='取消',command=dialog.destroy).pack(side='right',padx=8)
        combo.bind('<<ComboboxSelected>>',load)
        combo.current(next((i for i,a in enumerate(accounts) if a.get('generation_mode')==MODE_MULTI),0)); load()

    def open_multi_reference_picker(self, parent, initial, on_save):
        dialog = tk.Toplevel(parent); dialog.title('勾选多张参考图'); dialog.geometry('1120x720')
        dialog.minsize(820,540); dialog.transient(parent); dialog.grab_set()
        body = ttk.Frame(dialog,padding=14); body.pack(fill='both',expand=True)
        editors,size = self._multi_reference_picker_body(body,initial)
        def close():
            dialog.destroy()
            if parent.winfo_exists():parent.grab_set()
        def accept():
            on_save(self._multi_reference_config_from_picker(initial,editors,size)); close()
        actions = ttk.Frame(body); actions.pack(fill='x',pady=(14,0))
        ttk.Button(actions,text='确定选择',command=accept).pack(side='right')
        ttk.Button(actions,text='取消',command=close).pack(side='right',padx=8)
        dialog.protocol('WM_DELETE_WINDOW',close)

    def install_multi_reference_account_editor(self, dialog, variables, widgets, current):
        """Swap only the explicit multi mode's reference row; leave old controls intact."""
        mode = variables.get('generation_mode'); single = widgets.get('reference_name')
        if mode is None or single is None:
            return
        dialog._multi_reference_draft_config = copy.deepcopy(current.get('multi_reference_config') or {})
        grid = single.grid_info(); panel = ttk.Frame(single.master)
        summary = tk.StringVar()
        ttk.Label(panel,textvariable=summary).pack(side='left',fill='x',expand=True)
        def accept(config):
            dialog._multi_reference_draft_config = copy.deepcopy(config); update_summary()
        ttk.Button(panel,text='勾选多张参考图…',command=lambda:self.open_multi_reference_picker(dialog,dialog._multi_reference_draft_config,accept)).pack(side='right')
        def update_summary():
            config = dialog._multi_reference_draft_config
            backgrounds = self.normalize_multi_reference_names(config.get('background_names'))
            characters = self.normalize_multi_reference_names(config.get('character_names'))
            summary.set(f'已选 {len(backgrounds)+len(characters)} 张（背景 {len(backgrounds)} / 形象 {len(characters)}）')
        def mode_changed(*_):
            if mode.get()==MODE_MULTI:
                single.grid_remove(); panel.grid(row=grid['row'],column=grid['column'],sticky='ew',pady=5)
            else:
                panel.grid_remove(); single.grid()
        update_summary(); mode.trace_add('write',mode_changed); mode_changed()

    def collect_multi_reference_account_editor(self, dialog, mode, current):
        if mode!=MODE_MULTI:
            return None
        config = copy.deepcopy(dialog._multi_reference_draft_config)
        self.multi_reference_binding(dict(current,generation_mode=MODE_MULTI,multi_reference_config=config))
        return config
