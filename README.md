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
>
> **v2.0.3 绘图重做**：统一布局引擎 + SVG 重绘 —— 规整 slot 网格、模块框不重叠、
> 正交走线（stub → 垂直支线 → 水平主干）、单引脚网络也完整出线、彩色网络名标签、
> 标题栏/点阵网格/元件卡片，下载地址见 [绘图效果预览](docs/circuit-preview.html)。
>
> **v2.0.4 KiCad 原理图重做**：从「零导线 + 每引脚一个标签」改为**真实 wire + junction 连接**；
> 每条网络只保留 1 个标签（13→3），Reference/Value 移到符号外侧，竖线统一走列间空隙不穿元件，
> 未连接引脚自动打 no_connect，纸张按内容自适应 A4/A3。KiCad 10 ERC 复验通过。
>
> **v2.0.5 PCB 重做**：`.kicad_pcb` 不再是「板框 + 两行文字」的空壳 —— 从本机 KiCad 官方封装库
> （155 个 `.pretty`）读入**真实封装**（焊盘 / 丝印 / courtyard / 3D 模型），焊盘按网表挂
> `(net N "NAME")`；按 courtyard 真实尺寸做「模块成块 + 流式换行」排版，板框自适应内容并倒圆角，
> 大板自动加 4 个 M3 安装孔。三套模板 DRC 实测：**0 重叠、0 越界、0 短接**。
> [PCB 效果预览 →](docs/pcb-preview.html) ｜ [桌面版下载与使用说明 →](docs/DESKTOP-INSTALL.md)
>
> **v2.1.0 板子库扩充**：离线模板从 3 块扩到 **23 块**，覆盖电源 / LED 灯光 / 传感器 / 驱动 / 接口
> 五大类（TP4056 充电、LM2596 降压、4017 流水灯、MQ-2 报警、ULN2003 步进、MAX485、ESP-01 底板…）。
> 新增 15 种器件符号（NE555 / CD4017 / LM393 / LM386 / MAX485 / TP4056 / ULN2003 / LM2596 / 继电器 /
> MOSFET / 电位器 / 蜂鸣器 / 光敏 / 各类传感器模块），全部模板经 KiCad 10 实跑 **ERC + DRC 0 错误**；
> 原理图通道改为「就近模块间隙布线」，多网络大板不再拉一栅栏竖线，竖版内容自动改用 A4/A3 竖版纸。
> [板子库一览 →](docs/board-library.html)

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
- **PCB 是真正可用的板子**（v2.0.5 重做）：内联 KiCad 官方库封装（焊盘 / 丝印 / courtyard / 3D 模型），
  焊盘挂真实网络；按 courtyard 尺寸做模块化排版自动折行，板框按内容自适应并倒圆角，大板自动加 M3 安装孔；
  库里没有对应封装时按管脚数合成规整封装，**没装 KiCad 的机器也能出图**
- **板子库 23 块板子**（v2.1.0 扩充）：按电源 / LED 灯光 / 传感器 / 驱动 / 接口分类，语义加权打分选型，
  前端可按分类筛选直接套用；新增 15 种真实器件符号（NE555、CD4017、LM393、LM386、MAX485、TP4056、
  ULN2003、LM2596、SRD 继电器、AO3400、电位器、蜂鸣器、光敏电阻、传感器模块…）
- **三级能力降级**：自定义 LLM Key → 免费在线 LLM → 离线模板，**任何环境都能跑通**
- **自动产出三份报告**：工作汇报、操作指南、硬件需求清单

### 交互与桌面端
- **可下载安装的桌面应用**：原生窗口（WebView2）、Inno Setup 安装包、桌面 / 开始菜单快捷方式、可卸载；
  另有免安装单文件 exe；GitHub Actions 自动构建并发布到 Releases
- **丰富交互**：快捷指令卡片、模板库、实时理解预览、建议 chips、消息复制 / 重发、斜杠指令与键盘快捷键
- **规整的实时构图**（v2.0.3 重做）：统一布局引擎（slot 网格 + 模块分块 + 自动避让，元件卡片与模块框零重叠），正交走线「引脚 stub → 垂直支线 → 水平主干」，每条网络都完整出线（含单引脚网络）、彩色网络名标签、引脚端点、标题栏与点阵网格；样式内嵌 SVG，下载后独立打开也完整。[效果预览](docs/circuit-preview.html)
- **舞台工具**：缩放 / 拖拽 / 适应 / 全屏 / 重播 / 下载 SVG，三种板色实时重绘
- **结果工作台**：6 个标签页（含**可编辑的设计 JSON**）、单份导出、复制、打开输出目录、打印 PDF、唤起 KiCad
- **设置与主题**：运行时切换 LLM 配置、强制离线、实时解析开关、深浅双主题（本地持久化）

## 🧰 板子库（23 块）

左侧「板子库」可按分类筛选，点一下直接套用；也可以在对话框里描述需求（比如「做一个 MQ-2 气体报警板」），
由 NLU 加权语义匹配自动选板。每块板都能一键生成完整的 `.kicad_sch` / `.kicad_pcb` / `.kicad_pro` / BOM / 网表。

### 电源（5 块）

| 板子 | 核心器件 / 方案 | 元件 | 网络 |
| --- | --- | --- | --- |
| **5V 转 3.3V LDO 稳压** | AMS1117-3.3 线性稳压，含输入输出滤波电容与接线端子 | 6 | 3 |
| **LM7805 5V 线性稳压** | 经典 TO-220 三端稳压，100uF 输入输出储能 + 100nF 高频去耦 | 6 | 3 |
| **LM2596 5V 2A 降压** | 开关降压方案：33uH 储能电感 + SS34 续流肖特基 + 反馈取样 | 8 | 4 |
| **TP4056 锂电充电板** | 1A 恒流恒压充电，1.2k 设定电流，充电/充满双色状态灯 | 11 | 8 |
| **5V / 3.3V 双路电源** | LM7805 一级降压 + AMS1117 二级稳压，单片机与传感器常用供电 | 9 | 4 |

### LED 灯光（6 块）

| 板子 | 核心器件 / 方案 | 元件 | 网络 |
| --- | --- | --- | --- |
| **LED 指示灯电路** | 电源指示灯 + 限流电阻，元件最少，适合入门与快速验证 | 3 | 3 |
| **LED 闪烁电路** | ATmega328P 最小系统 + 晶振 + 复位 + LED 闪烁，完整 MCU 电路 | 10 | 7 |
| **NE555 无稳态闪灯** | 555 多谐振荡器闪灯，电阻电容决定频率，纯硬件无需编程 | 8 | 7 |
| **CD4017 六路流水灯** | 555 提供时钟 + 4017 十进制计数，六路 LED 依次点亮，可用电位器调速 | 19 | 18 |
| **RGB 三色灯板** | 共阴 RGB 灯珠，红绿蓝三路独立限流，四线接口直接接 MCU | 7 | 7 |
| **MOSFET 灯带调光** | AO3400 低边开关驱动 12V 灯带，支持 PWM 调光，栅极带下拉与滤波 | 6 | 5 |

### 传感器（5 块）

| 板子 | 核心器件 / 方案 | 元件 | 网络 |
| --- | --- | --- | --- |
| **DHT11 温湿度板** | DHT11 温湿度模块，10k 数据上拉 + 100nF 去耦 + 电源指示 | 6 | 4 |
| **DS18B20 测温板** | 单总线数字测温，4.7k 上拉电阻，TO-92 直插封装 | 4 | 3 |
| **HC-SR04 超声波板** | 超声波测距模块，Echo 5V 输出用 1k/2k 分压成 3.3V 电平 | 5 | 5 |
| **光控开关（LM393）** | 光敏电阻分压 + LM393 比较，电位器调阈值，输出带指示灯 | 9 | 6 |
| **MQ-2 气体报警板** | 可燃气体检测，LM393 比较阈值后驱动蜂鸣器与红灯，可输出报警信号 | 11 | 8 |

### 驱动（4 块）

| 板子 | 核心器件 / 方案 | 元件 | 网络 |
| --- | --- | --- | --- |
| **继电器驱动板** | S8050 三极管驱动 SRD-05VDC 继电器，1N4148 续流 + 吸合指示灯 | 9 | 9 |
| **ULN2003 步进电机** | 达林顿阵列驱动 28BYJ-48 五线步进电机，四路输入直接接 MCU | 5 | 10 |
| **蜂鸣器驱动板** | 有源蜂鸣器 + NPN 驱动，基极限流下拉、续流二极管、状态灯齐全 | 8 | 6 |
| **LM386 音频功放** | 音频功放，电位器调音量，输入输出耦合电容 + 电源旁路 | 8 | 8 |

### 接口（3 块）

| 板子 | 核心器件 / 方案 | 元件 | 网络 |
| --- | --- | --- | --- |
| **ESP-01 WiFi 底板** | ESP-01S 转接板：AMS1117 3.3V 供电、复位按键、串口与使能上拉 | 10 | 7 |
| **MAX485 通信接口** | RS-485 收发器，120R 终端电阻 + 总线偏置，DE/RE 方向控制引出 | 8 | 7 |
| **I2C OLED 接口板** | 0.96 寸 SSD1306 屏座，4.7k I2C 上拉与去耦电容 | 5 | 4 |

> 全部 23 块板子都用 KiCad 10.0.7 的 `kicad-cli` 实跑过：**ERC 0 错误、DRC 0 错误**，
> 原理图有真实 wire/junction、PCB 内联官方封装焊盘与 3D 模型。复验脚本：`scripts/validate_templates.py`。

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

去仓库 **Releases** 下载 `EDA-Agent-Setup-v2.1.0.exe` 双击安装，或下载 `EDA-Agent.exe` 免安装直接双击。
安装后有开始菜单 / 桌面快捷方式，卸载走控制面板。完整说明见 [桌面版安装指南](docs/DESKTOP-INSTALL.md)。

自己构建：

```powershell
pip install -r requirements-desktop.txt
powershell -ExecutionPolicy Bypass -File scripts\build_desktop.ps1
# 产物：dist\EDA-Agent.exe 与 dist\installer\EDA-Agent-Setup-v2.1.0.exe
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
│   ├── kicad_gen/
│   │   ├── layout.py               # ★ 统一布局引擎（slot 网格 / 模块框 / 网络通道）
│   │   ├── render_svg.py           # ★ 实时构图 SVG（正交走线 / 自包含样式）
│   │   ├── schematic.py            #   JSON → .kicad_sch
│   │   └── pcb.py / project.py     #   .kicad_pcb / 工程与库表
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
├── docs/                           # 设计报告 / 安装指南 / 演示脚本 / circuit-preview.html（绘图效果预览）
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
