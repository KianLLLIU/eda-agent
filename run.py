# -*- coding: utf-8 -*-
"""EDA Agent 启动入口

用法：
    python run.py                      # 默认 127.0.0.1:8000
    python run.py --host 0.0.0.0 --port 8080
    python run.py --reload             # 开发模式

启动后浏览器访问 http://127.0.0.1:8000
"""

import argparse
import os
import sys

# 确保 backend 包可导入
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def main():
    parser = argparse.ArgumentParser(description="EDA Agent 电路设计智能体")
    parser.add_argument("--host", default="127.0.0.1", help="监听地址")
    parser.add_argument("--port", type=int, default=8000, help="监听端口")
    parser.add_argument("--reload", action="store_true", help="开发热重载")
    args = parser.parse_args()

    import uvicorn
    from backend.main import app  # 直接导入 app 对象，兼容 PyInstaller 打包
    print("=" * 52)
    print("  EDA Agent · AI 电路设计智能体")
    print(f"  访问地址: http://{args.host}:{args.port}")
    print("  API 文档: http://127.0.0.1:%d/docs" % args.port)
    print("=" * 52)
    uvicorn.run(app, host=args.host, port=args.port, reload=args.reload)


if __name__ == "__main__":
    main()
