# EDA Agent · AI 电路设计智能体

> 说一句人话，换一块电路板。输入自然语言需求，AI 智能体自动完成「元器件选型 → 网表连接 → KiCad 原理图」，并生成工作汇报、操作指南与硬件需求清单。

这是《AI Agent 电路板设计》课程大作业的实现：一个「会画板子的 AI」，采用 **KiCad + LLM Agent** 技术路线。

---

> **v2.0 更新**：新增本地 NLU 引擎（意图分类 + 实体抽取 + 同义词词典）、统一对话入口与多轮会话、
> 大幅扩充的交互面板，以及**可下载安装的 Windows 桌面应用**（原生窗口 + 安装包 + CI 自动发布）。
>
> **v2.0.1 修复**：重写 KiCad 安装探测（手动路径 → 注册表卸载项 → 常见目录/各盘符 → 快捷方式 → PATH），
> 解决「KiCad 装在自定义目录时检测不到」的问题；设置面板可手动指定路径、查看探测诊断。
>
> **v2.0.2 修复**：生成的 KiCad 工程文件按 KiCad 9/10 官方格式重写，解决用 KiCad 打开时报
> `Unknown token 'uuid'` / 原理图加载失败。现已用 KiCad 10.0.7 的 `kicad-cli` 实测通过。
> [桌面版下载与使用说明 →](docs/DESKTOP-INSTALL.md)

## ✨ 功能特性

### Agent 与对话助手
- **本地 NLU 引擎**：10 类意图加权分类（生成 / 修改 / 解释 / 导出 / 模板 / 帮助 / 状态 / 重绘 / 新建 …），
  40+ 组电路术语同义词词典，中英文混输、简写别名、拼写容错，输出带类别与置信度的结构化理解
- **实体抽取**：自动识别元件编号（C1 / R2）、参数值（100nF / 330Ω / 3.3V / 16MHz）、数量、动作动词与接口
- **理解结果注入 Prompt**：把预解析结果交给 LLM，显著降低参数幻觉；输入时前端实时预览识别结果
- **有信息量的助手**：动态欢迎语、完整能力档案、上下文记忆、识别结果回显、主动澄清与下一步建议
- **离线也能改图**：「把 C1 换成 100nF」「增加一组 100nF 去耦电容」由本地规则引擎执行，不依赖 LLM
- **电路原理解释**：基于真实 design JSON 讲解模块划分、器件作用、网络走向与供电路径
- **多轮会话持久化**：会话历史保存 / 切换 / 删除，桌面端重启自动恢复上次设计

### 设计与工程
- **自然语言 → BOM / 网表**：结构化 JSON 约束 + 符号目录，生成元器件清单与引脚级连接
- **JSON → KiCad 原理图**：生成真实可打开的 `.kicad_sch` / `.kicad_pcb` / `.kicad_pro`
- **加权模板匹配**：3 套离线模板按语义打分选型，替代原先「首个关键词命中」
- **三级能力降级**：自定义 LLM Key → 免费在线 LLM → 离线模板，**任何环境都能跑通**
- **自动产出三份报告**：工作汇报、操作指南、硬件需求清单

### 交互与桌面端
- **可下载安装的桌面应用**：原生窗口（WebView2）、Inno Setup 安装包、桌面 / 开始菜单快捷方式、可卸载；
  另有免安装单文件 exe；GitHub Actions 自动构建并发布到 Releases
- **丰富交互**：快捷指令卡片、模板库、实时理解预览、建议 chips、消息复制 / 重发、斜杠指令与键盘快捷键
- **舞台工具**：缩放 / 拖拽 / 适应 / 全屏 / 重播 / 下载 SVG，三种板色实时重绘
- **结果工作台**：6 个标签页（含**可编辑的设计 JSON**）、单份导出、复制、打开输出目录、打印 PDF、唤起 KiCad
- **设置与主题**：运行时切换 LLM 配置、强制离线、实时解析开关、深浅双主题（本地持久化）

## 🏗️ 技术架构

```
自然语言输入
   │
   ▼
┌─────────────────────────────────────────────┐
│  Agent 编排层（backend/agent）                │
│  ① 需求解析  ② BOM 生成  ③ 网表 JSON          │
│  （LLM 模式 / 离线模板模式，自动降级）          │
└──────────────────┬──────────────────────────┘
                   │ design.json
                   ▼
┌─────────────────────────────────────────────┐
│  KiCad 生成器（backend/kicad_gen）            │
│  JSON → .kicad_sch / .kicad_pcb / .kicad_pro │
│  （网络标签连接 · 模块化布局 · BOM/网表导出）   │
└──────────────────┬──────────────────────────┘
                   ▼
          KiCad 可打开的原理图 + 报告
```

- **后端**：Python 3.10+ / FastAPI
- **LLM**：OpenAI 兼容接口（DeepSeek / OpenAI / 通义千问 / Ollama 等）
- **前端**：原生 HTML/CSS/JS（无构建依赖，单进程托管）

## 🚀 快速开始

### 方式一：桌面应用（推荐，无需 Python）

去仓库 **Releases** 下载 `EDA-Agent-Setup-v2.0.2.exe` 双击安装，或下载 `EDA-Agent.exe` 免安装直接双击。
安装后有开始菜单 / 桌面快捷方式，卸载走控制面板。完整说明见 [桌面版安装指南](docs/DESKTOP-INSTALL.md)。

自己构建：

```powershell
pip install -r requirements-desktop.txt
powershell -ExecutionPolicy Bypass -File scripts\build_desktop.ps1
# 产物：dist\EDA-Agent.exe 与 dist\installer\EDA-Agent-Setup-v2.0.2.exe
```

推一个 `v*` 标签即可让 GitHub Actions 自动构建安装包并发布 Release。

### 方式二：源码运行（5 分钟跑通）

### 环境要求

| 依赖 | 版本 | 说明 |
|------|------|------|
| Python | 3.10+ | Agent 主战场 |
| KiCad | 8 / 9 / 10 | 打开生成的原理图（**未安装也能生成文件**） |
| LLM API | 可选 | 未配置则自动使用离线模板 |

### 安装与运行

```bash
# 1. 克隆仓库
git clone <你的仓库地址>
cd eda-agent

# 2. 安装依赖
pip install -r requirements.txt

# 3. 启动
python run.py

# 4. 浏览器打开
#    http://127.0.0.1:8000
```

### 配置 LLM（可选）

**默认开箱即用**：不配置任何密钥时，系统自动使用**免费在线 LLM**（BlockRun 托管的开源模型，
无需注册、无需 key，每个用户都能直接用真实大模型生成电路）。

```bash
# Windows PowerShell（可选：改用你自己的 LLM，覆盖免费默认）
$env:EDA_AGENT_API_KEY="你的密钥"
$env:EDA_AGENT_BASE_URL="https://api.deepseek.com/v1"
$env:EDA_AGENT_MODEL="deepseek-chat"

# Linux / macOS
export EDA_AGENT_API_KEY="你的密钥"
export EDA_AGENT_BASE_URL="https://api.deepseek.com/v1"
export EDA_AGENT_MODEL="deepseek-chat"
```

三级能力（自动降级，保证任何环境下都能跑通）：
1. **自定义 LLM**：配置了 API Key（DeepSeek / OpenAI / 通义 / Ollama 等任意 OpenAI 兼容服务）
2. **免费在线 LLM**：无 key 时用 BlockRun 免费开源模型（默认，需能访问外网）
3. **离线模板**：免费 LLM 也不可用（如内网）时，按关键词匹配内置模板

> 关闭免费 LLM：设 `EDA_AGENT_NO_FREE_LLM=1`（例如内网无法访问海外服务时，直接走离线模板）。

## 📂 项目结构

```
eda-agent/
├── run.py                          # 网页版启动入口（浏览器）
├── desktop_launcher.py             # 桌面版启动入口（PyInstaller 入口点）
├── requirements.txt                # 运行依赖
├── requirements-desktop.txt        # 桌面构建依赖
├── backend/
│   ├── main.py                     # FastAPI 服务（REST API + 静态托管）
│   ├── config.py                   # 配置（环境变量 + 运行时设置 + 桌面路径）
│   ├── agent/
│   │   ├── nlu.py                  # ★ NLU 引擎（意图 / 实体 / 词典 / 加权模板）
│   │   ├── assistant.py            # ★ 对话助手（能力档案 / 会话 / 动态回复 / 电路解释）
│   │   ├── llm.py                  #   LLM 客户端（OpenAI 兼容，配置热更新）
│   │   ├── prompts.py              #   Prompt 设计（注入 NLU 理解与会话上下文）
│   │   ├── validator.py            #   JSON 校验兜底
│   │   └── pipeline.py             #   编排管线（含离线修订引擎）
│   ├── kicad_gen/                  # KiCad 生成器（自研，未改动）
│   ├── reports/                    # 报告生成器
│   └── templates/                  # 内置离线模板
├── desktop/
│   └── app.py                      # ★ 原生窗口外壳 + 本地服务同进程 + 浏览器降级
├── frontend/
│   ├── index.html                  # ★ 交互工作台骨架
│   ├── app.js                      # ★ 全部交互逻辑（统一走 /api/chat）
│   ├── styles.css                  # 基础设计系统
│   └── styles-v2.css               # ★ 新组件 + 深色主题
├── packaging/
│   ├── eda_agent.spec              # 旧版 console 打包（保留兼容）
│   └── eda_agent_desktop.spec      # ★ 桌面 GUI 单文件打包
├── installer/
│   └── EDA-Agent.iss                # ★ Inno Setup 安装脚本
├── scripts/
│   ├── build_desktop.ps1           # ★ 一键构建（exe + 安装包）
│   ├── make_icon.py                # ★ 图标生成
│   └── build_exe.*                 # 旧版构建脚本
├── assets/                         # ★ 应用图标 ico / png
├── .github/workflows/
│   └── build-desktop.yml           # ★ CI 自动构建 + Release 发布
├── docs/                           # 设计报告 / 安装指南 / 演示脚本
└── docker/                         # 网页版容器化部署
```

## 🔧 API 一览

### v2.0 新增

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/chat` | **统一对话入口**：意图路由 + 上下文 + 动态回复 + 结果一次返回 |
| POST | `/api/analyze` | 实时 NLU 预览（意图 / 关键词 / 实体 / 置信度 / 澄清） |
| GET | `/api/capabilities` | 助手能力档案、快捷指令、模板库、动态欢迎语 |
| GET / POST | `/api/templates` / `/api/template` | 离线模板列表与一键套用 |
| GET | `/api/history` | 会话列表；`/activate` 恢复、`DELETE` 删除 / 清空 |
| POST | `/api/session/new` | 新建会话 |
| GET / POST | `/api/settings` | 运行时配置（LLM Key / 模型 / 主题，API Key 不落盘） |
| POST | `/api/render` | 仅重绘 SVG（切换板色，无需重建工程） |
| POST | `/api/export` | 单份导出 BOM / 网表 / 报告 / JSON / 完整报告 |
| POST | `/api/design-from-json` | 编辑后的设计 JSON → 重新生成工程 |
| POST | `/api/open-folder` · GET `/api/file` | 打开输出目录 · 下载单个文件 |
| GET | `/api/kicad` | KiCad 探测详情（路径 / 版本 / 来源 / 检查过的位置） |
| POST | `/api/kicad/detect` · `/api/kicad/config` | 强制重新探测 · 手动指定 kicad.exe 路径 |
| GET | `/api/app-info` | 桌面端 / 版本 / 路径信息 |

### v1 兼容接口（全部保留）

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/health` · `/api/status` | 健康检查 · 运行状态 |
| POST | `/api/generate` | 自然语言 → 设计 JSON |
| POST | `/api/build` | 设计 JSON → 工程文件 + 报告 |
| POST | `/api/design` | 一步到位 |
| POST | `/api/revision` | 对话式修改（LLM 优先，离线规则兜底） |
| GET | `/api/download?path=` | 下载工程包 zip |
| POST | `/api/open-kicad` | 唤起本机 KiCad |

交互式 API 文档见 `http://127.0.0.1:8000/docs`。

## 📚 参考与致谢（学术诚信声明）

本项目在实现过程中参考了以下开源项目与资料（均为 MIT / 开源许可）：

- [skidl](https://github.com/devbisme/skidl) — Python 电路网表描述库（MIT），参考其「电路即代码」思想
- [PCBGPT](https://github.com/tk-king/pcbGPT) — 自然语言 PCB 设计助手，参考其 FastAPI + 前端架构
- [Circuitron](https://github.com/Shaurya-Sethi/circuitron) — Agent 化 PCB 设计，参考其多 Agent 编排思路
- [KiCad 官方文档](https://docs.kicad.org) — `.kicad_sch` / `.kicad_pcb` s-expression 文件格式

KiCad 原理图生成器（`backend/kicad_gen/`）为本项目**独立实现**，符号库、网络标签连接、模块化布局均为自研，未直接复用上述项目代码。

## ⚠️ 免责声明

本项目为课程学习用途，AI 生成的电路仅供学习参考。量产或用于安全关键系统前，必须由专业工程师审核。

## 📄 License

MIT License · 详见 [LICENSE](LICENSE)
