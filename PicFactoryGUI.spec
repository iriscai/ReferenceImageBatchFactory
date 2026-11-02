# -*- mode: python ; coding: utf-8 -*-


TK_PYTHON = r'C:\Users\74319\tmp_py313_smoke'


a = Analysis(
    ['launch_gui.py'],
    pathex=[],
    binaries=[
        (TK_PYTHON + r'\_tkinter.pyd', '.'),
        (TK_PYTHON + r'\tcl86t.dll', '.'),
        (TK_PYTHON + r'\tk86t.dll', '.'),
        (TK_PYTHON + r'\zlib1.dll', '.'),
    ],
    datas=[
        ('data', 'data'),
        ('picfactory_matrix.db', '.'),
        (TK_PYTHON + r'\Lib\tkinter', 'tkinter'),
        (TK_PYTHON + r'\_tcl_data', '_tcl_data'),
        (TK_PYTHON + r'\_tk_data', '_tk_data'),
    ],
    hiddenimports=[
        '_tkinter',
        'tkinter',
        'tkinter.ttk',
        'tkinter.filedialog',
        'tkinter.messagebox',
        'tkinter.scrolledtext',
        'image_clarity',
        'image_splitter',
        'image_refine',
        'image_refine.imaging',
        'image_refine.presets',
        'image_refine.schemas',
        'pydantic',
        'batch_v10_01_text',
        'naturalize_jfif_small_sharp_v10',
        'numpy',
        'PIL',
        'PIL.Image',
        'PIL.ImageOps',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='PicFactoryGUI',
    icon='assets\\reference_batch_icon.ico',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='PicFactoryGUI',
)
