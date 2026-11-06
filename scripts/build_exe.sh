#!/usr/bin/env bash
# 构建 macOS / Linux 单文件可执行（PyInstaller）
# 用法：bash scripts/build_exe.sh
set -e
cd "$(dirname "$0")/.."

echo "==> 安装 PyInstaller..."
pip install pyinstaller -q

echo "==> 开始打包..."
pyinstaller --clean -y packaging/eda_agent.spec

echo ""
echo "==> 打包完成！输出：dist/eda-agent"
echo "运行：./dist/eda-agent 然后访问 http://127.0.0.1:8000"
