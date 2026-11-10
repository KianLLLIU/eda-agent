# EDA Agent 桌面版 · 下载安装与使用指南

> 说一句人话，换一块电路板。本文说明如何把 EDA Agent 装到 Windows 桌面上使用。

## 一、两种产物，选一个就行

| 文件 | 说明 | 适合谁 |
|------|------|--------|
| `EDA-Agent-Setup-v2.0.0.exe` | **安装程序**（推荐）。有开始菜单、可选桌面快捷方式、控制面板可卸载、带版本信息与图标 | 普通使用者、交作业演示 |
| `EDA-Agent.exe` | **免安装便携版**。单个 exe，双击即用，拷到 U 盘也能跑 | 不想装软件、机房 / 临时电脑 |

两者功能完全一致，区别只在「有没有安装向导和快捷方式」。

## 二、从哪里下载

### 方式 A：GitHub Releases（最省事）

打开仓库 → 右侧 **Releases** → 下载最新版里的 `EDA-Agent-Setup-*.exe`。

如果 Release 里还没有文件，说明还没触发构建。在仓库 **Actions → Build Desktop App → Run workflow** 手动跑一次；或推一个标签自动构建并发布：

```bash
git tag v2.0.0
git push origin v2.0.0
```

CI 会在 Windows 上自动完成：装依赖 → 生成图标 → PyInstaller 单文件打包 → Inno Setup 编译安装包 → 发布到 Release（同时保留 30 天构建产物）。

### 方式 B：本机一键构建

需要 Python 3.10+（建议 3.11），在项目根目录执行：

```powershell
pip install -r requirements-desktop.txt
powershell -ExecutionPolicy Bypass -File scripts\build_desktop.ps1
```

产物在 `dist\`。若本机装了 **Inno Setup 6**，脚本会顺带编译出安装包；没装也不会失败，仍然得到便携版 exe。

### 方式 C：源码直接跑桌面窗口（不打包）

```bash
pip install -r requirements-desktop.txt
python desktop_launcher.py            # 原生窗口
python desktop_launcher.py --browser  # 强制浏览器模式
python run.py                         # 传统网页版（浏览器打开）
```

## 三、系统要求

| 项目 | 要求 |
|------|------|
| 操作系统 | Windows 10 / 11 x64 |
| 内存 | 建议 4 GB 以上 |
| 磁盘 | 安装版约 60~120 MB |
| Python | **不需要**（exe 已内置运行时） |
| 网络 | **不需要**（离线模板 + 本地 NLU 全程可用；联网时可选启用 LLM） |
| KiCad | 可选。仅「用 KiCad 打开工程」按钮需要，生成文件本身不依赖 KiCad |
| WebView2 | Windows 10/11 通常自带；缺失时程序自动改用默认浏览器，不会闪退 |

## 四、安装步骤

1. 双击 `EDA-Agent-Setup-v2.0.0.exe`；
2. 若弹出 UAC 提示，点「是」；
3. 选择安装位置（默认 `C:\Program Files\EDA Agent`），可勾选「创建桌面快捷方式」；
4. 点安装，完成后可直接勾选「运行 EDA Agent」；
5. 之后从**开始菜单 / 桌面快捷方式**启动即可，无需命令行、无需浏览器地址栏。

> 安装程序不会覆盖你的设计数据。会话历史、设置、生成的工程都放在用户目录 `~\.eda-agent\` 与 `~\eda-agent-output\`，卸载程序也**不会删除**它们。

## 五、首次使用

启动后是一个独立窗口（不是浏览器标签页），左栏是智能助手，右栏是原理图舞台与报告。

1. 点一张**快捷指令**卡片，或直接输入：`做一个 5V 转 3.3V 的 LDO 稳压电路，带输入输出滤波电容`；
2. 输入时下方会实时显示**识别到的意图、置信度、关键词与参数**；
3. 回车发送，右侧会播放元件逐个摆放、连线逐条绘制的构图动画；
4. 结果区可切换 BOM / 网表 / 工作汇报 / 操作指南 / 硬件需求 / **可编辑的设计 JSON**；
5. 继续说「把 C1 换成 100nF」即可迭代改图，离线也能改。

常用操作：

- 舞台工具条：缩放、适应、拖拽平移、全屏、重播动画、下载 SVG；
- 结果工具条：下载工程 zip、单份导出 BOM / 网表 / JSON / 完整报告、复制、打开输出目录、打印 PDF；
- 顶栏：新建会话、历史会话、深浅主题、设置（LLM 配置）、能力清单；
- 快捷键：`Ctrl+K` 聚焦输入框、`Ctrl+N` 新建会话、`Esc` 关闭抽屉、输入框支持 `/help` 等斜杠指令。

## 六、为什么是这套技术方案

| 方案 | 体积 | 构建门槛 | 结论 |
|------|------|----------|------|
| Electron 壳 + Python 后端 | 150 MB+ | 需 Node 工具链、要管理后端子进程 | 太重，不划算 |
| Tauri | ~10 MB | 需 Rust 工具链，本机/CI 都要装 | 最优体积但落地成本高 |
| **pywebview + PyInstaller + Inno Setup** | 60~120 MB | 纯 Python，复用系统 WebView2 | **采用**：单语言、可做真安装程序、有降级路径 |
| PWA / 浏览器快捷方式 | 极小 | 低 | 不算「安装到桌面的应用」 |

关键取舍：**后端本来就是 Python FastAPI**，让原生窗口与本地服务跑在同一个进程里，省掉端口协商、子进程残留、路径找不全三类常见坑；同时保留「WebView2 不可用时自动打开浏览器」的兜底，任何 Windows 机器都能跑起来。

## 七、常见问题

**Q：双击没反应 / 闪退？**
先看 `~\.eda-agent\desktop.log`。多数情况是端口被占或资源路径异常，程序会自动换端口；若确实失败会弹窗说明原因。也可以先用 `--browser` 模式验证服务是否正常。

**Q：杀毒软件报毒？**
PyInstaller 单文件 exe 常被启发式引擎误报，属于常见误判。可从源码自行构建（方式 B/C），或在 CI 的构建产物里核对 SHA256。

**Q：窗口打不开，只弹出了浏览器？**
说明本机没有 WebView2 运行时。安装微软官方 **WebView2 Runtime** 后重启应用即可获得原生窗口；在浏览器模式下所有功能照常可用。

**Q：完全没有网络能用吗？**
能。本地 NLU 引擎、离线模板库、KiCad 文件生成、报告生成全部离线。想用大模型时，在「设置」里填 API Key 或保留免费在线 LLM；连不上会自动降级，不会报错卡死。

**Q：生成的文件在哪？**
`~\eda-agent-output\<会话 id>\<工程名>\`，点界面里的「打开输出目录」可直接跳转。

**Q：怎么彻底卸载？**
设置 → 应用 → EDA Agent → 卸载，或运行安装目录下的 `unins000.exe`。如需清理个人数据，再手动删除 `~\.eda-agent\` 与 `~\eda-agent-output\`（卸载程序故意保留，避免误删作业成果）。

## 八、开发者备注

- 打包入口：`desktop_launcher.py` → `desktop/app.py`；
- 打包配置：`packaging/eda_agent_desktop.spec`（`console=False`，单文件，带图标）；
- 安装脚本：`installer/EDA-Agent.iss`；
- 自动构建：`.github/workflows/build-desktop.yml`；
- 图标生成：`scripts/make_icon.py`（改配色后重跑即可）；
- 旧版网页入口 `run.py` 与 `packaging/eda_agent.spec` 全部保留，两种形态可共存。
