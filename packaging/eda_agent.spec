# -*- mode: python ; coding: utf-8 -*-
# PyInstaller 打包配置：把后端 + 前端 + 模板打成单个 exe
# 用法：pyinstaller packaging/eda_agent.spec

import os

root = os.path.abspath(os.path.join(os.path.dirname(SPECPATH), ".."))  # noqa: F821

datas = [
    (os.path.join(root, "frontend"), "frontend"),
    (os.path.join(root, "backend", "templates"), "backend/templates"),
]

a = Analysis(
    [os.path.join(root, "run.py")],
    pathex=[root],
    binaries=[],
    datas=datas,
    hiddenimports=["uvicorn.logging", "uvicorn.loops", "uvicorn.loops.auto", "uvicorn.protocols",
                   "uvicorn.protocols.http", "uvicorn.protocols.http.auto", "uvicorn.protocols.websockets",
                   "uvicorn.protocols.websockets.auto", "uvicorn.lifespan", "uvicorn.lifespan.on"],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter", "test", "unittest"],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="eda-agent",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,          # 控制台程序，便于打印访问地址
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
