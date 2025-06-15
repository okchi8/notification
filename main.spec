# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ["main.py"],
    pathex=[],
    binaries=[],
    datas=[
        ("config.ini", "."),
        ("cameras.json", "."),
        ("data/vip_list.csv", "data"), # Note: specify 'data/vip_list.csv' as source, 'data' as destination
        ("image_utils.py", "."),
        ("vip_manager.py", "."),
        ("telegram_notifier.py", "."),
        ("config_loader.py", "."),
        ("camera_handler.py", "."),
        ("http_listener.py", "."),
        ("test_digest_auth.py", ".")
    ],
    hiddenimports=[
        "flask",
        "werkzeug"
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
    a.binaries,
    a.datas,
    [],
    name='main', # Corrected line
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False, # Keep this as False for headless
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
