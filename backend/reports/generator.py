# -*- coding: utf-8 -*-
"""
报告生成器：为每一次设计自动产出三份文档
  - 工作汇报（设计说明）
  - 操作指南（如何打开/检查/改板/制板）
  - 硬件需求（BOM 采购清单 + 供电 + 工具）
"""

from __future__ import annotations

import datetime

from ..kicad_gen.bom import _grouped_bom


def _now():
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M")


def work_report(design, requirement, mode):
    """工作汇报"""
    comps = design.get("components", [])
    nets = design.get("nets", [])
    groups = design.get("groups", [])
    lines = []
    lines.append(f"# 电路设计工作汇报")
    lines.append("")
    lines.append(f"- 生成时间：{_now()}")
    lines.append(f"- 生成模式：{mode}")
    lines.append(f"- 设计名称：{design.get('title', '未命名')}")
    lines.append("")
    lines.append("## 一、需求描述")
    lines.append(f"> {requirement}")
    lines.append("")
    lines.append("## 二、方案概述")
    lines.append(f"本次设计共 **{len(comps)}** 个元件，**{len(nets)}** 条网络，"
                 f"划分为 **{len(groups)}** 个功能模块。")
    lines.append("")
    lines.append("## 三、功能模块划分")
    for g in groups:
        refs = "、".join(g.get("refs", []))
        lines.append(f"- **{g.get('name')}**：{refs}")
    lines.append("")
    lines.append("## 四、器件选型")
    lines.append("| 编号 | 参数 | 封装 |")
    lines.append("|------|------|------|")
    for c in comps:
        lines.append(f"| {c['ref']} | {c.get('value','')} | {c.get('footprint','')} |")
    lines.append("")
    lines.append("## 五、连接关系")
    for net in nets:
        conns = "、".join(f"{c['ref']}.{c['pin']}" for c in net["connections"])
        lines.append(f"- **{net['name']}**：{conns}")
    lines.append("")
    lines.append("## 六、待确认项")
    lines.append("- 器件参数值（阻容值、晶振频率）请结合实际需求复核；")
    lines.append("- 封装是否与采购器件一致需人工核对；")
    lines.append("- 供电电压与负载电流需按应用场景校核。")
    return "\n".join(lines)


def operation_guide(design, project_name):
    """操作指南"""
    lines = []
    lines.append(f"# 操作指南：{design.get('title', project_name)}")
    lines.append("")
    lines.append("## 一、用 KiCad 打开")
    lines.append(f"1. 启动 KiCad 8（或 9/10）；")
    lines.append(f"2. 打开工程文件 `{project_name}.kicad_pro`；")
    lines.append(f"3. 双击打开原理图 `{project_name}.kicad_sch`，即可查看电路。")
    lines.append("")
    lines.append("## 二、运行电气规则检查（ERC）")
    lines.append("1. 在原理图编辑器点击「检查 → 电气规则检查」；")
    lines.append("2. 查看报错与警告，重点处理「未连接引脚」；")
    lines.append("3. 本设计采用网络标签连接，同名标签即电气相连。")
    lines.append("")
    lines.append("## 三、修改设计")
    lines.append("- 直接拖动元件、修改参数值后重新标注；")
    lines.append("- 若要重新生成，修改 `design.json` 后重新运行生成脚本；")
    lines.append("- 或回到前端界面，输入修改需求（如「把电容换成 100nF」）重新生成。")
    lines.append("")
    lines.append("## 四、生成 PCB 与制板")
    lines.append("1. 打开 PCB 编辑器 `{project_name}.kicad_pcb`；")
    lines.append("2. 完成布局与布线（可先跑 DRC）；")
    lines.append("3. 导出 Gerber 与钻孔文件，交给板厂打样。")
    return "\n".join(lines)


def hardware_requirements(design):
    """硬件需求清单"""
    groups = _grouped_bom(design)
    lines = []
    lines.append(f"# 硬件需求清单：{design.get('title', '未命名')}")
    lines.append("")
    lines.append("## 一、元器件采购清单")
    lines.append("| 编号 | 数量 | 参数值 | 封装 |")
    lines.append("|------|------|--------|------|")
    for r in groups:
        lines.append(f"| {', '.join(r['refs'])} | {r['qty']} | {r['value']} | {r['footprint']} |")
    lines.append("")
    lines.append("## 二、供电要求")
    # 扫描 VCC/GND/VIN 等网络推断供电
    nets = {n["name"]: n for n in design.get("nets", [])}
    supply = [n for n in nets if n in ("VCC", "VIN", "5V", "3V3", "VOUT", "VBUS")]
    if supply:
        lines.append("- 电源网络：" + "、".join(supply))
    else:
        lines.append("- 请根据设计确定供电电压（常见 3.3V / 5V）。")
    lines.append("- 建议使用稳压电源或 USB 供电，注意输入电压范围与电流余量。")
    lines.append("")
    lines.append("## 三、工具与设备")
    lines.append("- KiCad 8+（查看与编辑设计文件）")
    lines.append("- 万用表（焊接后测试）")
    lines.append("- 烙铁 + 焊锡（手焊）或回流焊（贴片）")
    lines.append("- 示波器 / 逻辑分析仪（调试，可选）")
    lines.append("")
    lines.append("## 四、安全提示")
    lines.append("- 首次上电前务必核对电源极性，防止短路；")
    lines.append("- 大功率/高压电路需人工复核后再使用；")
    lines.append("- 本设计由 AI 生成，仅供学习参考，量产前需专业工程师审核。")
    return "\n".join(lines)
