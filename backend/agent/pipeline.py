# -*- coding: utf-8 -*-
"""
编排管线（Agent 的核心大脑）

自然语言 → 设计 JSON → KiCad 工程文件 + BOM + 报告

两种模式：
  1. LLM 模式：调用 OpenAI 兼容接口生成设计 JSON（需要 API Key）
  2. 模板模式：按关键词匹配内置模板（离线可用，保证「5 分钟跑通」）
"""

from __future__ import annotations

import json
import os
import shutil

from .. import config
from ..kicad_gen import (
    build_schematic,
    build_project,
    build_sym_lib_table,
    build_fp_lib_table,
    build_pcb,
    bom_csv,
    bom_markdown,
    netlist_markdown,
)
from .llm import LLMClient, LLMError, extract_json
from .prompts import SYSTEM_PROMPT, build_user_prompt
from .validator import validate_design, DesignError

# 内置模板索引
TEMPLATES = {
    "led_blink": ("LED 闪烁电路", "led_blink.json"),
    "led_indicator": ("LED 指示灯电路", "led_indicator.json"),
    "ldo_3v3": ("5V 转 3.3V LDO 稳压电路", "ldo_3v3.json"),
}

# 关键词 → 模板 的简单匹配规则
KEYWORD_RULES = [
    (["最小系统", "atmega", "arduino", "单片机", "闪烁", "blink", "led 闪烁"], "led_blink"),
    (["指示灯", "led", "发光"], "led_indicator"),
    (["降压", "稳压", "ldo", "3.3", "3v3", "电源", "转换"], "ldo_3v3"),
]


def _load_template(name):
    path = os.path.join(config.TEMPLATE_DIR, TEMPLATES[name][1])
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _match_template(requirement: str):
    req = requirement.lower()
    for keywords, tpl in KEYWORD_RULES:
        if any(k in req for k in keywords):
            return tpl
    return "led_indicator"


def generate_design_json(requirement: str, use_llm: bool = None):
    """自然语言 → 设计 JSON。返回 (design_dict, mode)"""
    client = LLMClient()
    if use_llm is None:
        use_llm = client.available

    if use_llm:
        try:
            content = client.chat(
                [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": build_user_prompt(requirement)},
                ],
                temperature=0.1,
                json_mode=True,
            )
            design = extract_json(content)
            return validate_design(design), "llm"
        except (LLMError, DesignError) as e:
            # LLM 失败时降级到模板模式，保证可用性
            tpl = _match_template(requirement)
            return _load_template(tpl), f"template(降级: {e})"
    else:
        tpl = _match_template(requirement)
        return _load_template(tpl), "template"


def build_project_files(design: dict, output_dir: str, project_name: str = "circuit"):
    """
    将设计 JSON 生成为完整的 KiCad 工程文件，写入 output_dir。
    返回生成的文件路径字典。
    """
    os.makedirs(output_dir, exist_ok=True)

    name = design.get("title", "circuit")
    sch_text = build_schematic(design)
    pro_text = build_project(project_name, name)
    pcb_text = build_pcb(design)
    sym_table = build_sym_lib_table(project_name)
    fp_table = build_fp_lib_table()

    files = {
        "schematic": os.path.join(output_dir, f"{project_name}.kicad_sch"),
        "project": os.path.join(output_dir, f"{project_name}.kicad_pro"),
        "pcb": os.path.join(output_dir, f"{project_name}.kicad_pcb"),
        "sym_lib_table": os.path.join(output_dir, "sym-lib-table"),
        "fp_lib_table": os.path.join(output_dir, "fp-lib-table"),
        "bom_csv": os.path.join(output_dir, "BOM.csv"),
        "bom_md": os.path.join(output_dir, "BOM.md"),
        "netlist_md": os.path.join(output_dir, "NETLIST.md"),
        "design_json": os.path.join(output_dir, "design.json"),
    }

    with open(files["schematic"], "w", encoding="utf-8") as f:
        f.write(sch_text)
    with open(files["project"], "w", encoding="utf-8") as f:
        f.write(pro_text)
    with open(files["pcb"], "w", encoding="utf-8") as f:
        f.write(pcb_text)
    with open(files["sym_lib_table"], "w", encoding="utf-8") as f:
        f.write(sym_table)
    with open(files["fp_lib_table"], "w", encoding="utf-8") as f:
        f.write(fp_table)
    with open(files["bom_csv"], "w", encoding="utf-8") as f:
        f.write(bom_csv(design))
    with open(files["bom_md"], "w", encoding="utf-8") as f:
        f.write(bom_markdown(design))
    with open(files["netlist_md"], "w", encoding="utf-8") as f:
        f.write(netlist_markdown(design))
    with open(files["design_json"], "w", encoding="utf-8") as f:
        json.dump(design, f, ensure_ascii=False, indent=2)

    return files


def package_project(output_dir: str, project_name: str) -> str:
    """把 output_dir 打包成 zip，返回 zip 路径"""
    zip_base = os.path.join(os.path.dirname(output_dir), f"{project_name}_kicad")
    shutil.make_archive(zip_base, "zip", output_dir)
    return zip_base + ".zip"
