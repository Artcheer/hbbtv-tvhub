# -*- mode: python -*-
# Build único (onefile) do TVHub. Gere com:  pyinstaller TVHub.spec
a = Analysis(
    ['app.py'],
    pathex=[],
    binaries=[],
    datas=[('templates', 'templates'), ('static', 'static')],
    hiddenimports=[],
    hookspath=[],
    runtime_hooks=[],
    excludes=['playwright', 'unittest', 'tkinter'],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    name='TVHub',
    debug=False,
    strip=False,
    upx=False,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
)
