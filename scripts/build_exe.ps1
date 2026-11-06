# 构建 Windows 安装包（PyInstaller 单文件 exe）
# 用法：在项目根目录执行  powershell -ExecutionPolicy Bypass -File scripts/build_exe.ps1

$ErrorActionPreference = "Stop"
Set-Location (Split-Path $PSScriptRoot -Parent)

Write-Host "==> 安装 PyInstaller..."
pip install pyinstaller -q

Write-Host "==> 开始打包（单文件 exe）..."
pyinstaller --clean -y packaging/eda_agent.spec

Write-Host ""
Write-Host "==> 打包完成！输出文件："
Write-Host "   dist/eda-agent.exe"
Write-Host ""
Write-Host "运行方式：双击 dist/eda-agent.exe，然后浏览器访问 http://127.0.0.1:8000"
