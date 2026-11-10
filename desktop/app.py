# -*- coding: utf-8 -*-
"""
EDA Agent 桌面应用外壳
=======================

架构：单个进程内同时跑
  · uvicorn（后台线程，只监听 127.0.0.1，不对外暴露）
  · pywebview 原生窗口（Windows 使用系统自带 WebView2 / Edge Chromium）

为什么这样选：
  · 后端是 Python FastAPI，同进程托管免去「启动子进程 + 端口协商 + 进程残留」的坑；
  · pywebview 体积远小于 Electron（~1MB vs ~150MB），复用系统 WebView2，无需打包 Chromium；
  · 安装程序（Inno Setup）负责开始菜单 / 桌面快捷方式 / 卸载，是真正的「安装到桌面」。

降级策略（很重要）：
  若运行环境没有 WebView2 运行时或 pywebview 未打包成功，自动退化成
  「启动本地服务 + 打开默认浏览器」，功能完全不受影响，不会白屏或闪退。
"""

from __future__ import annotations

import argparse
import os
import socket
import sys
import threading
import time
import urllib.request
import webbrowser

# 保证源码运行 / PyInstaller 打包运行都能导入 backend 包
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

APP_TITLE = "EDA Agent · AI 电路设计智能体"
DEFAULT_WIDTH = 1440
DEFAULT_HEIGHT = 920
MIN_WIDTH = 1080
MIN_HEIGHT = 700


def find_free_port(start=8765, max_tries=200):
    """找一个空闲端口；桌面端每次启动都用新端口，避免与浏览器版 / 多开冲突"""
    for p in range(start, start + max_tries):
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(0.2)
        try:
            if s.connect_ex(("127.0.0.1", p)) != 0:
                return p
        finally:
            s.close()
    return start


class ServerThread(threading.Thread):
    """在后台线程运行 uvicorn，主线程留给 GUI 事件循环"""

    def __init__(self, host: str, port: int):
        super().__init__(daemon=True)
        self.host = host
        self.port = port
        self.server = None
        self.error = None

    def run(self):
        try:
            import uvicorn
            from backend.main import app  # 延迟导入，等资源路径就绪
            config = uvicorn.Config(
                app, host=self.host, port=self.port,
                log_level="warning", access_log=False,
            )
            self.server = uvicorn.Server(config)
            self.server.run()
        except Exception as e:  # noqa: BLE001
            self.error = e

    def stop(self):
        if self.server is not None:
            self.server.should_exit = True


def wait_until_ready(url: str, timeout: float = 30.0) -> bool:
    """等本地服务真正就绪再开窗，避免窗口先出来显示连接失败"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url + "/api/health", timeout=1.0) as r:
                if r.status == 200:
                    return True
        except Exception:
            pass
        time.sleep(0.2)
    return False


class DesktopApi:
    """暴露给前端的原生能力（window.pywebview.api.*）

    前端不依赖这些也能完整工作；这里提供的是「桌面应用才做得到」的增强：
    原生保存对话框、打开输出目录、读取应用信息、主动退出。
    """

    def __init__(self, window_ref=None):
        self._window = window_ref

    def get_app_info(self):
        from backend import config
        return {
            "name": config.APP_NAME,
            "version": config.APP_VERSION,
            "frozen": config.IS_FROZEN,
            "desktop": True,
            "data_dir": config.USER_DATA_DIR,
            "output_dir": config.OUTPUT_DIR,
        }

    def open_output_folder(self):
        from backend import config
        path = os.path.abspath(config.OUTPUT_DIR)
        os.makedirs(path, exist_ok=True)
        try:
            if sys.platform == "win32":
                os.startfile(path)  # noqa: S606
            elif sys.platform == "darwin":
                os.system('open "%s"' % path)
            else:
                os.system('xdg-open "%s"' % path)
            return {"ok": True, "path": path}
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "error": str(e), "path": path}

    def save_text(self, filename, content):
        """原生「另存为」对话框，把文本写到用户选择的位置"""
        try:
            import webview
            win = self._window or (webview.windows[0] if webview.windows else None)
            if win is None:
                return {"ok": False, "error": "窗口不可用"}
            result = win.create_file_dialog(
                webview.SAVE_DIALOG,
                save_filename=str(filename),
                file_types=("所有文件 (*.*)",),
            )
            if not result:
                return {"ok": False, "cancelled": True}
            target = result if isinstance(result, str) else result[0]
            with open(target, "w", encoding="utf-8") as f:
                f.write(str(content))
            return {"ok": True, "path": target}
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "error": str(e)}

    def quit_app(self):
        try:
            import webview
            if webview.windows:
                webview.windows[0].destroy()
            return {"ok": True}
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "error": str(e)}


def _start_webview(url: str, debug: bool = False):
    """尝试创建原生窗口；返回 True 表示成功接管了主线程"""
    try:
        import webview  # 动态导入：缺失时直接走浏览器降级，不影响打包
    except Exception as e:  # noqa: BLE001
        print("[EDA Agent] Native window unavailable (%s), using browser fallback." % e)
        return False

    try:
        api = DesktopApi()
        window = webview.create_window(
            APP_TITLE,
            url,
            width=DEFAULT_WIDTH, height=DEFAULT_HEIGHT,
            min_size=(MIN_WIDTH, MIN_HEIGHT),
            resizable=True,
            text_select=True,
            confirm_close=False,
            js_api=api,
            background_color="#F5F6F8",
        )
        api._window = window
        # Windows 上优先使用 EdgeChromium(WebView2)，退而求其次用其它可用后端
        try:
            webview.start(gui="edgechromium", debug=debug)
        except Exception:
            webview.start(debug=debug)
        return True
    except Exception as e:  # noqa: BLE001
        print("[EDA Agent] Failed to create window (%s), using browser fallback." % e)
        return False


def run_desktop(host="127.0.0.1", port=None, debug=False, force_browser=False):
    """启动桌面应用，窗口关闭后返回"""
    os.environ["EDA_AGENT_DESKTOP"] = "1"
    port = port or find_free_port()
    url = "http://%s:%d" % (host, port)

    server = ServerThread(host, port)
    server.start()

    if not wait_until_ready(url, timeout=30):
        print("[EDA Agent] 本地服务启动超时：%s" % (server.error or "unknown"))
        return 1

    print("=" * 60)
    print("  EDA Agent Desktop  v2.0")
    print("  Local service : %s" % url)
    print("  Mode          : %s" % ("browser fallback" if force_browser else "native window"))
    print("=" * 60)

    used_webview = False
    if not force_browser:
        used_webview = _start_webview(url, debug=debug)

    if not used_webview:
        # Browser fallback: keep this process alive as long as the local server runs.
        # Never rely on input() here -- a windowed exe has no console/stdin, and an
        # immediate EOF would terminate the app right after the first request.
        try:
            webbrowser.open(url)
        except Exception as e:  # noqa: BLE001
            print("[EDA Agent] Could not open browser automatically (%s)." % e)
            print("[EDA Agent] Open %s manually." % url)
        print("Opened in browser. Press CTRL+C to stop the service.")
        try:
            while server.is_alive():
                time.sleep(0.5)
        except KeyboardInterrupt:
            pass

    server.stop()
    return 0


def main():
    parser = argparse.ArgumentParser(description="EDA Agent Desktop")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=None)
    parser.add_argument("--browser", action="store_true", help="强制用浏览器打开（调试 / 无 WebView2 环境）")
    parser.add_argument("--debug", action="store_true", help="开启 WebView 开发者工具")
    args = parser.parse_args()
    return run_desktop(args.host, args.port, args.debug, args.browser)


if __name__ == "__main__":
    sys.exit(main())
