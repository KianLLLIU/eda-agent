# -*- coding: utf-8 -*-
"""
Prompt 设计（自然语言 → BOM + 网表 JSON）

设计思路（对应课程作业「Prompt 设计」要求）：
  1. 用「结构化 JSON 约束」防止幻觉：明确列出可用符号及其引脚编号，
     要求模型只在给定符号表内选型、只用给定引脚号连接。
  2. 用「网络标签连接约定」约束输出：所有引脚连接关系写入 nets[]，
     电源（VCC/GND）也以普通网络形式列出，便于生成器统一处理。
  3. 用「示例（few-shot）」锚定输出格式：给出一个最小完整示例，稳定结构。
  4. 分两步走（可选）：先出 BOM，再出连接关系；单步合并为一次 JSON 输出，
     降低往返开销，同时保留 BOM/网表两个清晰字段。
"""

from __future__ import annotations

import json

from ..kicad_gen.symbols import SYMBOL_LIB


def _symbol_catalog() -> str:
    """生成可用符号目录（符号名 + 引脚列表），注入 prompt 以约束选型。"""
    lines = []
    for lib_id, sym in SYMBOL_LIB.items():
        pins = ", ".join(f"{p[0]}={p[1]}" for p in sym["pins"])
        lines.append(f"- {lib_id}  （引脚: {pins}）")
    return "\n".join(lines)


SYSTEM_PROMPT = """你是一名资深硬件电路设计工程师，擅长把用户的自然语言需求转换成可制造的标准电路设计。

你的任务：根据用户描述，输出一份**电路设计 JSON**，包含：
1. 元器件清单（BOM）——从「可用符号表」中选型；
2. 引脚级连接关系（网表）——明确每个网络的连接引脚。

严格遵守以下规则：
- 只使用「可用符号表」中列出的符号（lib:symbol 必须完全一致）；
- 引脚号必须与符号表中该符号的引脚号一致，不得编造引脚；
- 每个需要连接的引脚都必须出现在某个网络的 connections 里；
- 电源（VCC/GND 等）用普通网络表达，例如网络 "GND" 连接所有接地引脚；
- 网络命名使用大写英文字母与下划线（如 VCC、GND、NET_LED）；
- 元件编号（ref）唯一，如 R1、R2、C1、U1、LED1、Y1、J1；
- 输出必须是合法 JSON，不要输出任何解释文字。
"""


def build_user_prompt(requirement: str) -> str:
    catalog = _symbol_catalog()
    schema = {
        "title": "电路名称",
        "groups": [{"name": "模块名", "refs": ["R1", "U1"]}],
        "components": [
            {"ref": "R1", "lib": "Device", "symbol": "R", "value": "10k",
             "footprint": "Resistor_SMD:R_0805_2012Metric"}
        ],
        "nets": [
            {"name": "NET_LED", "connections": [
                {"ref": "R1", "pin": "1"}, {"ref": "LED1", "pin": "2"}]}
        ],
    }
    example = json.dumps(schema, ensure_ascii=False, indent=2)

    return f"""可用符号表（只能使用这些符号，引脚号必须匹配）：
{catalog}

输出 JSON 结构如下（请严格遵循字段与类型）：
{example}

字段说明：
- groups：功能模块分组，refs 为该模块包含的元件编号列表（用于原理图分模块排版）；
- components：每个元件含 ref（唯一编号）、lib（符号库）、symbol（符号名）、
  value（参数值）、footprint（封装，格式"库:封装名"）；
- nets：网络列表，每个网络 name 唯一，connections 为该网络连接的所有引脚。

用户需求：
{requirement}

请输出电路设计 JSON（仅 JSON，不要其它文字）：
"""
