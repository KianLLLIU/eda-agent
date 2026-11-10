# -*- mode: python ; coding: utf-8 -*-
# PyInstaller 打包配置：EDA Agent 桌面应用（原生窗口单文件 exe）
#
# 用法（在项目根目录执行）：
#   pyinstaller --clean -y packaging/eda_agent_desktop.spec
# 产物：dist/EDA-Agent.exe  —— 可直接双击运行，也是安装包的主程序
#
# 与 eda_agent.spec（旧版 console 浏览器模式）的区别：
#   · console=False：没有黑色控制台窗口，是真正的 GUI 应用
#   · 入口换成 desktop_launcher.py，内含原生窗口与浏览器降级
#   · 带应用图标，供 Inno Setup 创建桌面 / 开始菜单快捷方式

import importlib.util
import os

root = os.path.abspath(os.getcwd())

icon_path = os.path.join(root, "assets", "eda-agent.ico")
icon = icon_path if os.path.isfile(icon_path) else None

datas = [
    (os.path.join(root, "frontend"), "frontend"),
    (os.path.join(root, "backend", "templates"), "backend/templates"),
]

hiddenimports = [
    "uvicorn.logging", "uvicorn.loops", "uvicorn.loops.auto",
    "uvicorn.protocols", "uvicorn.protocols.http", "uvicorn.protocols.http.auto",
    "uvicorn.protocols.websockets", "uvicorn.protocols.websockets.auto",
    "uvicorn.lifespan", "uvicorn.lifespan.on",
    "backend.main", "backend.config",
    "backend.agent", "backend.agent.nlu", "backend.agent.assistant",
    "backend.agent.pipeline", "backend.agent.llm",
    "backend.agent.prompts", "backend.agent.validator",
    "backend.kicad_gen", "backend.kicad_gen.schematic",
    "backend.kicad_gen.pcb", "backend.kicad_gen.project",
    "backend.kicad_gen.bom", "backend.kicad_gen.symbols",
    "backend.kicad_gen.render_svg", "backend.reports",
    "desktop", "desktop.app",
]

# pywebview 是可选增强：装了才打包，没装则自动降级到浏览器模式，构建照样成功
if importlib.util.find_spec("webview") is not None:
    hiddenimports += [
        "webview", "webview.platforms", "webview.platforms.edgechromium",
        "webview.platforms.winforms", "webview.platforms.mshtml",
    ]

a = Analysis(
    [os.path.join(root, "desktop_launcher.py")],
    pathex=[root],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter", "test", "unittest", "pytest", "matplotlib", "numpy"],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="EDA-Agent",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    runtime_tmpdir=None,
    console=False,              # GUI 应用：无控制台黑窗
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=icon,
    version=None,
)
