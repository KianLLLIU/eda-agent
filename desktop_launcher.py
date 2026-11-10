# -*- coding: utf-8 -*-
"""
EDA Agent 桌面版启动入口（PyInstaller 入口点）

用法：
    python desktop_launcher.py                 # 原生窗口
    python desktop_launcher.py --browser      # 强制浏览器模式（调试用）
    EDA-Agent.exe                            # 打包后双击运行

windowed 打包时没有控制台，这里负责：
  1. 把 stdout/stderr 安全重定向到用户数据目录的 desktop.log（否则 print 会崩）；
  2. 启动失败时用系统弹窗告知用户，而不是静默闪退。
"""

from __future__ import annotations

import os
import sys
import traceback

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def _setup_streams():
    """Windowed builds have no console: give stdout/stderr a UTF-8 log file.

    A real interactive terminal keeps its console output; everything else
    (PyInstaller --windowed, IDE, redirected run) writes to
    ~/.eda-agent/desktop.log so startup errors are always diagnosable.
    """
    try:
        interactive = sys.stdout is not None and sys.stdout.isatty()
    except Exception:
        interactive = False
    if interactive and sys.stderr is not None:
        return
    try:
        log_dir = os.path.join(os.path.expanduser("~"), ".eda-agent")
        os.makedirs(log_dir, exist_ok=True)
        f = open(os.path.join(log_dir, "desktop.log"), "a", encoding="utf-8", buffering=1)
    except Exception:
        f = open(os.devnull, "w", encoding="utf-8")
    sys.stdout = f
    sys.stderr = f


def _fatal(msg: str):
    """windowed 模式下用系统弹窗暴露错误"""
    try:
        import ctypes
        ctypes.windll.user32.MessageBoxW(0, msg, "EDA Agent 启动失败", 0x10)
    except Exception:
        pass
    try:
        print("[FATAL] " + msg, file=sys.stderr, flush=True)
    except Exception:
        pass


def main():
    _setup_streams()
    try:
        from desktop.app import main as desktop_main
        return desktop_main()
    except Exception as e:  # noqa: BLE001
        detail = "%s: %s\n\n%s" % (type(e).__name__, e, traceback.format_exc())
        _fatal("应用启动失败：%s\n\n详细信息已写入 ~/.eda-agent/desktop.log" % e)
        print(detail, file=sys.stderr, flush=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())
