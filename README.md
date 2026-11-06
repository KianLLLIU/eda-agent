# EDA Agent · AI 电路设计智能体

> 说一句人话，换一块电路板。输入自然语言需求，AI 智能体自动完成「元器件选型 → 网表连接 → KiCad 原理图」，并生成工作汇报、操作指南与硬件需求清单。

这是《AI Agent 电路板设计》课程大作业的实现：一个「会画板子的 AI」，采用 **KiCad + LLM Agent** 技术路线。

---

## ✨ 功能特性

- **自然语言 → BOM**：设计 Prompt，让 LLM 从一句话需求生成元器件清单
- **自然语言 → 网表**：LLM 进一步给出引脚级连接关系，输出结构化 JSON
- **JSON → KiCad 原理图**：用 Python 脚本把 JSON 变成真实可打开的 `.kicad_sch` / `.kicad_pcb` / `.kicad_pro`
- **交互式修正**：修改需求（如「把电容换成 100nF」）即可重新生成
- **自动产出三份报告**：工作汇报、操作指南、硬件需求清单
- **双模式运行**：有 LLM API Key 走真实大模型；无 Key 走内置模板，**保证离线也能跑通**
- **精美交互界面**：深空科技风 Web UI，实时展示生成流水线

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

## 🚀 快速开始（5 分钟跑通）

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

### 配置 LLM（可选，推荐）

```bash
# Windows PowerShell
$env:EDA_AGENT_API_KEY="你的密钥"
$env:EDA_AGENT_BASE_URL="https://api.deepseek.com/v1"
$env:EDA_AGENT_MODEL="deepseek-chat"

# Linux / macOS
export EDA_AGENT_API_KEY="你的密钥"
export EDA_AGENT_BASE_URL="https://api.deepseek.com/v1"
export EDA_AGENT_MODEL="deepseek-chat"
```

不配置任何密钥也能跑：系统会按关键词自动匹配内置模板（Arduino 最小系统、LED 指示灯、5V→3.3V 稳压）。

## 📂 项目结构

```
eda-agent/
├── run.py                 # 启动入口
├── requirements.txt       # 依赖
├── backend/
│   ├── main.py            # FastAPI 服务（REST API + 静态托管）
│   ├── config.py          # 全局配置（环境变量）
│   ├── agent/             # Agent 编排层
│   │   ├── llm.py         #   LLM 客户端（OpenAI 兼容）
│   │   ├── prompts.py     #   Prompt 设计（符号目录约束 + few-shot）
│   │   ├── validator.py   #   JSON 校验兜底
│   │   └── pipeline.py    #   编排管线（NL → JSON → 文件）
│   ├── kicad_gen/         # KiCad 生成器（自研）
│   │   ├── symbols.py     #   符号库（数据驱动）
│   │   ├── schematic.py   #   JSON → .kicad_sch
│   │   ├── pcb.py         #   JSON → .kicad_pcb
│   │   ├── project.py     #   .kicad_pro + 库表
│   │   └── bom.py         #   BOM / 网表导出
│   ├── reports/           # 报告生成器（工作汇报/操作指南/硬件需求）
│   └── templates/         # 内置离线模板
├── frontend/              # 交互界面（原生三件套）
├── docs/                  # 设计报告 / 操作指南 / 硬件需求 / 工作总结
├── packaging/             # PyInstaller 打包配置
└── docker/                # 网站版容器化部署
```

## 🔧 API 一览

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/status` | LLM / KiCad 状态 |
| POST | `/api/generate` | 自然语言 → 设计 JSON |
| POST | `/api/build` | 设计 JSON → 工程文件 + 报告 |
| POST | `/api/design` | 一步到位（上面两步合并） |
| GET | `/api/download?path=` | 下载生成工程包（zip） |

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
