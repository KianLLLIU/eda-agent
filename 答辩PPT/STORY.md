# STORY.md — AI Agent 电路板设计答辩

## ① 用户意图对齐

- **目标受众**：课程大作业现场答辩评审（任课老师 + 助教），5 分钟讲清「教会 AI 画电路板」。
- **核心目标**：让评审相信——① 打通了「自然语言 → KiCad 原理图」完整流水线；② 关键设计决策（选型、连接、Prompt）我能讲清原理；③ 系统真实可运行、有实验结果与失败反思。
- **PPT 长度**：13 页（Hero 3 页，占比 23%）。
- **视觉调性**：学术严谨 / 蓝白克制 / 证据驱动 / 层次清晰。
- **内容边界**：必讲「技术路线、Agent 架构、Prompt 设计、KiCad 生成器、实验结果、失败案例」；不讲「行业趋势空话、营销话术」；禁碰「代做/抄袭等学术诚信红线」。

## ② 页面布局骨架

**分章（3 章）**：
- 01 项目概述 → 第 4、5 页
- 02 核心设计 → 第 7、8、9 页
- 03 成果与反思 → 第 11、12 页

**目录↔章节扉页契约**：目录声明 3 章，对应 3 个 `section` 扉页——第 3 页「01 项目概述」、第 6 页「02 核心设计」、第 10 页「03 成果与反思」，编号连续、标题与目录逐字一致。

**Hero 页定位**：封面（1）、实验结果（11）、结束页（13），占比 23%，任意两个 Hero 间隔 ≥1 个 Supporting 页。

**rhythm 曲线**：
- 1 封面 peak → 2 目录 valley → 3 扉页 transition → 4 概述 valley → 5 技术路线 peak → 6 扉页 transition → 7 架构 valley → 8 Prompt valley → 9 KiCad valley → 10 扉页 transition → 11 实验 peak → 12 反思 valley → 13 结束 peak
- 连续 valley 最多 3 页（7/8/9），其后 10 为 transition，未超 3 页。

**版式预算**：content 页共 7 页，非对称 6 页（86% ≥40%），对称仅第 8 页（N卡片横排 1 次 ≤2）。

## ③ 页面大纲

| 页 | title | type | role | rhythm | layout | visual | visual_role | density | anti_pattern | description |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 | 封面 | cover | hero | peak | 全屏视觉+大标题 | L1: 电路板线稿 SVG（全幅背景） | atmosphere | 字约40 / 图1 / 留白45% | 禁红金印章、烟花、人物大头照 | 中英标题+单位+汇报人+时间 |
| 2 | 目录 | catalog | supporting | valley | 左标题+右内容 | L3: 章节编号 | evidence | 字约60 / 留白30% | 禁圆球编号、书法数字 | 3 章目录+摘要 |
| 3 | 01 项目概述 | section | transition | transition | 居中大字 | L1: 流程 SVG（半幅） | atmosphere | 字约60 / 留白50% | 禁四卡预览、铺满正文 | 章节扉页：大数字 01 + 标题 + 3 要点 |
| 4 | 一句话项目 | content | supporting | valley | 左标题+右内容 | L1: 输入输出对比 SVG（右侧 55%） | evidence | 字约180 / 图1 / 留白18% | 禁50:50等分、装饰小图 | 一句话讲清「自然语言→电路板」+ 五步走基础任务 |
| 5 | 技术路线 | content | supporting | peak | 流程时间轴（非对称） | L1: 六步流水线 Diagram（全幅） | anchor | 字约150 / 图1 / 留白15% | 禁等宽卡片横排 | 六步：NL→LLM→JSON→KiCad→原理图→DRC 闭环 |
| 6 | 02 核心设计 | section | transition | transition | 居中大字 | L1: 流程 SVG（半幅） | atmosphere | 字约60 / 留白50% | 禁四卡预览 | 章节扉页：大数字 02 + 标题 + 3 要点 |
| 7 | Agent 架构 | content | supporting | valley | 左大图+右侧文字 | L1: 架构 Diagram（左 55%） | anchor | 字约160 / 图1 / 留白18% | 禁单栏线性列表 | 前端+Agent 编排+KiCad 生成器+三级 LLM 降级 |
| 8 | Prompt 设计 | content | supporting | valley | N卡片横排 | L3: 编号方块 | evidence | 字约330 / 留白15% | 禁深蓝实色卡、卡尾无锚 | 防幻觉三招：符号目录约束+few-shot+结构化JSON |
| 9 | KiCad 生成器 | content | supporting | valley | 非对称双栏 | L1: 原理图 SVG（左 45%） | evidence | 字约200 / 图1 / 留白18% | 禁上下等分 | 自研 s-expression 生成 + 网络标签连接 + 模块化布局 |
| 10 | 03 成果与反思 | section | transition | transition | 居中大字 | L1: 流程 SVG（半幅） | atmosphere | 字约60 / 留白50% | 禁四卡预览 | 章节扉页：大数字 03 + 标题 + 3 要点 |
| 11 | 实验结果 | content | hero | peak | 巨型数字+洞察 | 大数字（最小 72px） | anchor | 字约120 / 留白30% | 禁把数字塞进图表卡角落 | 13 元件/7 网络 Arduino 最小系统 + 免费LLM 生成成功 |
| 12 | 失败案例 | content | supporting | valley | 非对称双栏 | L2: 失败→解决对照 | evidence | 字约240 / 留白18% | 禁上下等分、空卡片 | 坐标系翻转/中文文件名/LLM不可信 三案例+解决 |
| 13 | 总结致谢 | ending | hero | peak | 居中金句 | L3: 学校 logo | atmosphere | 字约40 / 留白45% | 禁烟花金饰 | 一句话总结 + 致谢 + 开源致谢 |
