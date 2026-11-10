# 工作日志（WORKLOG）

> 课程大作业「AI Agent 电路板设计」开发日志。仓库即成长日记，每一次关键进展都在此记录。

---

## 阶段 0：需求理解与环境准备（W1）

- [x] 阅读大作业宣讲，明确「自然语言 → 原理图」五步走基础任务（40 分）与进阶挑战（20 分）
- [x] 确认技术路线：KiCad + LLM Agent
- [x] 调研开源方案：skidl（电路即代码）、PCBGPT（NL→KiCad 架构）、Circuitron（多 Agent 编排）
- [x] 确定自研 KiCad 原理图生成器（掌握 s-expression 文件格式，便于答辩解释）

**关键决策**：不直接复用第三方 KiCad 生成代码，而是自己实现 `JSON → .kicad_sch`，
既能吃透格式，又符合学术诚信「关键设计决策能口头解释」的要求。

## 阶段 1：最小闭环（W3–W4）

- [x] 数据驱动的符号库（R/C/L/LED/二极管/晶振/三端稳压器/排针/ATmega328P）
- [x] `JSON → .kicad_sch` 生成器：网络标签连接、模块化布局、lib_symbols 内嵌
- [x] `JSON → .kicad_pcb` 基础版（板框 + 元件摆放）
- [x] BOM / 网表导出（CSV + Markdown）
- [x] 冒烟测试通过（生成 13KB 有效原理图）

**踩坑记录**：
1. KiCad 符号局部坐标 y 轴向上、原理图 y 轴向下，计算引脚世界坐标必须先翻转 y，
   否则旋转元件引脚错位——采用「所有符号水平定义、rotation=0」规避。
2. power 符号（GND/VCC）不实例化，电源网络统一用 net label 连接，避免 KiCad 10
   的 `power_in` 引脚需物理导线才能建网的问题。

## 阶段 2：Agent 编排 + 交互界面（W5–W6）

- [x] LLM 客户端（OpenAI 兼容接口，支持 DeepSeek / OpenAI / 通义 / Ollama）
- [x] Prompt 设计：符号目录约束（防幻觉）+ few-shot 示例 + 结构化 JSON 输出
- [x] JSON 校验兜底：编号唯一、符号存在、引脚合法，非法输出自动拦截
- [x] 离线模板模式：无 API Key 时按关键词匹配内置模板，保证 5 分钟跑通
- [x] FastAPI 后端：`/api/generate` `/api/build` `/api/design` `/api/download`
- [x] 深空科技风前端：输入需求 → 流水线可视化 → BOM/网表/三份报告 → 下载工程包
- [x] 端到端测试通过（health / status / design / download / 静态资源）

## 阶段 3：报告产出 + 打包部署（W7）

- [x] 报告生成器：每次设计自动产出「工作汇报 / 操作指南 / 硬件需求」三份文档
- [x] PyInstaller 安装包配置（Windows exe）
- [x] Docker 容器化（网站版 / 云部署）
- [x] README（环境要求 + 安装步骤 + 运行命令，助教 5 分钟跑起来）

## 阶段 4：文档与提交（W8）

- [x] 设计报告、操作指南、硬件需求、工作总结
- [x] 提交物齐全：代码仓库（含 README）、设计报告、演示所需素材
- [ ] 录制 3–5 分钟演示视频
- [ ] 答辩 PPT

---

## 提交物清单对照

| 要求 | 状态 |
|------|------|
| 代码仓库（含 README） | ✅ |
| 设计报告 | ✅ `docs/设计报告.md` |
| 演示视频（3–5 分钟） | ⏳ 待录制 |
| 答辩 PPT | ⏳ 待制作 |

## 进阶挑战（已完成）

- **DRC 检查闭环**（部分）：生成器内置校验 + 设计文档标注 ERC/DRC 检查要点，可在 KiCad 中一键运行

---

## 阶段 5：UI 大改版 + 智能助手 + 实时构图（2026-11-06）

- [x] **浅色主题重做**：深色科技风 → 浅色设计系统（PCB 绿主色 + Space Grotesk/Noto Sans SC），更简洁克制
- [x] **难度选择**：入门（3~6 元件）/ 进阶（8~16）/ 挑战（完整系统），经 Prompt 约束 LLM 控制复杂度
- [x] **电路板风格选择**：经典绿 / 现代极简 / 复古暖铜，影响实时构图 SVG 配色与前端 accent
- [x] **智能聊天助手**：对话式设计，提取需求关键词（chips 高亮），支持「把电容换成 100nF」这类修改指令
- [x] **对话式实时修改**：新增 `/api/revision`，把修改指令 + 当前设计发给 LLM 重写，只改指定部分
- [x] **实时构图画面**：自研 `render_svg.py` 把设计 JSON 渲染成 SVG 原理图，前端做「元件逐个淡入、连线逐条画出」的实时构图动画
- [x] **一键打开 KiCad**：新增 `/api/open-kicad`，探测本机 KiCad 并打开生成的 `.kicad_pro`
- [x] **免费在线 LLM**（上一阶段遗留）：BlockRun 无 key 开源模型，三级降级（自定义 key → 免费 LLM → 离线模板）

### 关键技术点
- SVG 实时构图：后端 render_svg.py 复用 symbols.py 符号定义 + schematic.py 布局，元件/连线带 `data-i` 动画序号；前端 JS 计算连线 `getTotalLength` 做 stroke-dasharray 逐条画线动画。
- 对话式修改：`apply_revision()` 把当前 design JSON + 修改指令发给 LLM，输出修改后的完整 JSON，再走 `validate_design` 兜底。

---

## 阶段 6：答辩 PPT + 演示视频脚本（2026-11-10）

- [x] **答辩 PPT**（`答辩PPT/AI Agent电路板设计答辩.pptx`，13 页，学术风蓝白配色）：
  - 封面 / 目录 / 三个章节扉页 / 项目概述 / 技术路线 / Agent 架构 / Prompt 设计 / KiCad 生成器 / 实验结果 / 失败案例 / 总结致谢
  - 采用 tencent-pptx 学术风模板（主蓝 #1E4FA8 + 藏蓝 #0E3F8C，思源黑），目录↔章节扉页契约、Hero 页占比、非对称版式占比均合规
  - 源文件在 `答辩PPT/slides/*.slide`（STORY.md + DESIGN.md 可复现/改版）
- [x] **演示视频脚本**（`docs/演示视频脚本.md`）：7 幕分镜 + 逐秒旁白 + 字幕全文 + 录制注意事项，照着录即可

### 提交物清单更新

| 要求 | 状态 |
|------|------|
| 代码仓库（含 README） | ✅ |
| 设计报告 | ✅ `docs/设计报告.md` |
| 演示视频（3–5 分钟） | ⏳ 脚本已就绪，待照脚本录屏 |
| 答辩 PPT | ✅ `答辩PPT/AI Agent电路板设计答辩.pptx` |
