# -*- coding: utf-8 -*-
"""EDA Agent 启动入口

用法：
    python run.py                      # 自动找空闲端口 + 自动打开浏览器
    python run.py --port 8080          # 指定端口
    python run.py --no-browser         # 不自动打开浏览器
    python run.py --reload             # 开发模式（热重载）

双击打包后的 exe 同样会自动打开浏览器，端口被占用时自动切换。
"""

import argparse
import os
import socket
import sys
import threading
import webbrowser

# 确保 backend 包可导入（源码运行 / 打包运行均适用）
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def find_free_port(start=8000, max_tries=100):
    """从 start 开始找第一个空闲端口，找不到则返回 start"""
    for p in range(start, start + max_tries):
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(0.3)
        try:
            if s.connect_ex(("127.0.0.1", p)) != 0:
                return p
        finally:
            s.close()
    return start


def _open_browser(url):
    try:
        webbrowser.open(url)
    except Exception:
        pass


def main():
    parser = argparse.ArgumentParser(description="EDA Agent - AI Circuit Design Agent")
    parser.add_argument("--host", default="127.0.0.1", help="listen address")
    parser.add_argument("--port", type=int, default=None, help="listen port (default: auto-pick free port from 8000)")
    parser.add_argument("--no-browser", action="store_true", help="do not auto-open browser")
    parser.add_argument("--reload", action="store_true", help="dev hot reload")
    args = parser.parse_args()

    # 端口选择：未显式指定时，从 8000 起自动找空闲端口（避免冲突）
    if args.port is None:
        port = find_free_port(8000)
    else:
        port = args.port

    url = f"http://{args.host}:{port}"

    try:
        import uvicorn
        from backend.main import app  # 直接导入 app 对象，兼容 PyInstaller 打包
    except Exception as e:
        print("ERROR: failed to import app: %s" % e)
        try:
            input("Press Enter to exit...")
        except Exception:
            pass
        sys.exit(1)

    # 延迟自动打开浏览器（等服务真正就绪）
    if not args.no_browser:
        threading.Timer(1.2, _open_browser, args=(url,)).start()

    # 控制台提示用英文（避免 Windows 控制台 GBK 编码乱码）
    print("=" * 56)
    print("  EDA Agent  -  AI Circuit Design Agent")
    print("  Open:  %s" % url)
    print("  API docs:  http://127.0.0.1:%d/docs" % port)
    print("  Press CTRL+C to stop.")
    print("=" * 56)

    try:
        uvicorn.run(app, host=args.host, port=port, reload=args.reload)
    except Exception as e:
        print("ERROR: server failed to start: %s" % e)
        try:
            input("Press Enter to exit...")
        except Exception:
            pass
        sys.exit(1)


if __name__ == "__main__":
    main()
