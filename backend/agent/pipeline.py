# -*- coding: utf-8 -*-
"""
编排管线（Agent 的核心大脑）

自然语言 → 设计 JSON → KiCad 工程文件 + BOM + 报告

三种模式：
  1. LLM 模式：调用 OpenAI 兼容接口生成设计 JSON（需要 API Key 或免费在线 LLM）
  2. 模板模式：NLU 加权语义匹配内置模板（离线可用，保证「5 分钟跑通」）
  3. 离线修订：无 LLM 时，按「动作 + 元件 + 参数」规则直接改已有设计 JSON

v2.0 变化：
  - 关键词识别从 3 条 substring 规则升级为 nlu.py（意图 / 实体 / 同义词 / 模糊匹配 / 加权模板）
  - NLU 理解结果注入 LLM Prompt，显著降低参数幻觉
  - 对话式修改不再强依赖 LLM，离线也能改阻值 / 容值 / 增删元件 / 改名
"""

from __future__ import annotations

import copy
import json
import os
import re
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
from . import nlu
from .llm import LLMClient, LLMError, extract_json
from .prompts import SYSTEM_PROMPT, build_user_prompt
from .validator import validate_design, DesignError

# 内置模板索引
TEMPLATES = {
    "led_blink": ("LED 闪烁电路", "led_blink.json"),
    "led_indicator": ("LED 指示灯电路", "led_indicator.json"),
    "ldo_3v3": ("5V 转 3.3V LDO 稳压电路", "ldo_3v3.json"),
}

TEMPLATE_DESCRIPTIONS = {
    "led_blink": "ATmega328P 最小系统 + 晶振 + 复位 + LED 闪烁，适合演示完整 MCU 电路",
    "led_indicator": "电源指示灯 + 限流电阻，元件最少，适合入门与快速验证",
    "ldo_3v3": "AMS1117-3.3 线性稳压，含输入输出滤波电容与接线端子",
}


def _load_template(name):
    path = os.path.join(config.TEMPLATE_DIR, TEMPLATES[name][1])
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _match_template(requirement: str, analysis: dict = None):
    """加权语义匹配（保留旧函数名，供外部调用）"""
    if analysis:
        return analysis["template"]["best"]
    return nlu.match_template(requirement)[0]


def list_templates():
    """模板库清单（供前端模板卡片渲染）"""
    out = []
    for name, (label, filename) in TEMPLATES.items():
        path = os.path.join(config.TEMPLATE_DIR, filename)
        comps = nets = 0
        title = label
        try:
            with open(path, "r", encoding="utf-8") as f:
                d = json.load(f)
            comps = len(d.get("components", []))
            nets = len(d.get("nets", []))
            title = d.get("title", label)
        except Exception:
            pass
        out.append({
            "id": name, "name": label, "title": title,
            "description": TEMPLATE_DESCRIPTIONS.get(name, ""),
            "components": comps, "nets": nets,
            "signals": [s[0] for s in nlu.TEMPLATE_SIGNALS.get(name, [])[:6]],
        })
    return out


def load_template_by_name(name):
    if name not in TEMPLATES:
        raise DesignError("未知模板: %s" % name)
    return validate_design(_load_template(name))


# ---------------------------------------------------------------------------
# 生成
# ---------------------------------------------------------------------------
def generate_design_json(requirement: str, use_llm: bool = None,
                         difficulty: str = "intermediate",
                         analysis: dict = None, context: str = ""):
    """自然语言 → 设计 JSON。返回 (design_dict, mode)

    analysis: 预先算好的 NLU 结果（避免 /api/chat 重复解析）
    context:  多轮会话摘要
    """
    client = LLMClient()
    if use_llm is None:
        use_llm = client.available

    understanding = ""
    if analysis is None:
        analysis = nlu.analyze(requirement)
    understanding = nlu.to_prompt_hint(analysis)

    if use_llm:
        try:
            content = client.chat(
                [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": build_user_prompt(
                        requirement, difficulty, understanding=understanding, context=context)},
                ],
                temperature=0.1,
                json_mode=True,
            )
            design = extract_json(content)
            return validate_design(design), f"llm:{client.mode}"
        except (LLMError, DesignError) as e:
            # LLM 失败时降级到模板模式，保证可用性
            tpl = _match_template(requirement, analysis)
            return _load_template(tpl), f"template(降级: {e})"
    else:
        tpl = _match_template(requirement, analysis)
        return _load_template(tpl), "template"


# ---------------------------------------------------------------------------
# 对话式修改：LLM 优先，离线规则兜底
# ---------------------------------------------------------------------------
def _clean_value(text: str) -> str:
    """把「330 欧姆」「100nf」规范化成元件 value 字段"""
    v = str(text or "").strip()
    v = re.sub(r"\s+", "", v)
    v = v.replace("欧姆", "R").replace("Ω", "R").replace("ohm", "R").replace("OHM", "R")
    v = v.replace("µ", "u").replace("μ", "u")
    # 统一容值写法：100nf / 100NF / 100nF → 100nF
    v = re.sub(r"(?<=\d)([nup])f\b", lambda m: m.group(1) + "F", v, flags=re.I)
    v = re.sub(r"(?<=\d)mf\b", "mF", v, flags=re.I)
    # 10k → 10K（阻值简写）
    v = re.sub(r"(?<=\d)(k|m)$", lambda m: m.group(1).upper(), v, flags=re.I)
    return v


def _infer_category_from_value(value: str, instruction: str = ""):
    """按参数单位反推元件类别（用户没说「电容」但说了「100nF」时使用）"""
    v = (value + " " + instruction).lower()
    if re.search(r"(nf|uf|pf|mf|微法|纳法|皮法|farad|电容)", v):
        return "电容"
    if re.search(r"(\d\s*(k|r|ohm|ω|欧)|电阻|阻值|限流)", v):
        return "电阻"
    if re.search(r"(mhz|khz|晶振|频率)", v):
        return "晶振"
    if re.search(r"(\d\s*v|伏|电压|稳压)", v):
        return "稳压器"
    return None


def _find_targets(design: dict, analysis: dict, new_value: str):
    """定位要修改的元件：元件编号 > 关键词类别 > 参数单位反推"""
    comps = design.get("components", [])
    ents = analysis["entities"]

    if ents["refs"]:
        picked = [c for c in comps if c.get("ref", "").upper() in [r.upper() for r in ents["refs"]]]
        if picked:
            return picked, "按元件编号 " + "、".join(ents["refs"][:4])

    cats = list(ents["categories"])
    if not cats and new_value:
        inferred = _infer_category_from_value(new_value, analysis["text"])
        if inferred:
            cats = [inferred]
    for cat in cats:
        symbols = nlu.CATEGORY_TO_SYMBOL.get(cat, [])
        picked = [c for c in comps
                  if any("%s:%s" % (c.get("lib", ""), c.get("symbol", "")).startswith(s) for s in symbols)]
        if picked:
            return picked, "按类别「%s」" % cat
    return [], ""


def _apply_offline_revision(design: dict, instruction: str, analysis: dict):
    """离线规则修订引擎：不依赖 LLM 也能改图。

    支持：改参数值（阻值/容值/电压/频率）、改名、增删元件。
    返回 (new_design, changes:list[str])
    """
    d = copy.deepcopy(design)
    ents = analysis["entities"]
    actions = set(ents["actions"])
    changes = []

    # 新值：取指令里出现的第一个带单位参数值
    raw_values = ents["values"]
    new_value = _clean_value(raw_values[0]) if raw_values else ""

    # 1) 改电路名称
    m = re.search(r"(?:改名|名称改?为|标题改?为|叫)\s*[:：]?\s*([^\s，。,\.]{2,30})", instruction)
    if m:
        old = d.get("title", "")
        d["title"] = m.group(1).strip("\"'《》")
        changes.append("标题：%s → %s" % (old, d["title"]))

    comps = d.get("components", [])

    # 2) 删除元件
    if "remove" in actions and (ents["refs"] or ents["categories"]):
        targets, how = _find_targets(d, analysis, new_value)
        removed = {c.get("ref") for c in targets}
        if removed:
            d["components"] = [c for c in comps if c.get("ref") not in removed]
            for net in d.get("nets", []):
                net["connections"] = [x for x in net.get("connections", []) if x.get("ref") not in removed]
            d["nets"] = [n for n in d.get("nets", []) if n.get("connections")]
            for g in d.get("groups", []):
                g["refs"] = [r for r in g.get("refs", []) if r not in removed]
            d["groups"] = [g for g in d.get("groups", []) if g.get("refs")]
            changes.append("删除元件 %s（%s）" % ("、".join(sorted(removed)), how))

    # 3) 增加元件（复制同类样板，沿用其网络连接关系，保证图纸仍然合法）
    elif "add" in actions and new_value:
        cat = (ents["categories"] or [_infer_category_from_value(new_value, instruction)])[0]
        cat = cat or "电容"
        symbols = nlu.CATEGORY_TO_SYMBOL.get(cat, [])
        samples = [c for c in comps
                   if any("%s:%s" % (c.get("lib", ""), c.get("symbol", "")).startswith(s) for s in symbols)]
        if samples:
            sample = samples[0]
            prefix = re.match(r"([A-Za-z]+)", sample.get("ref", "X1"))
            prefix = prefix.group(1) if prefix else "X"
            used = {int(m.group(1)) for c in comps
                    for m in [re.fullmatch(re.escape(prefix) + r"(\d+)", c.get("ref", ""))] if m}
            new_ref = prefix + str(max(used or [0]) + 1)
            new_comp = copy.deepcopy(sample)
            new_comp["ref"] = new_ref
            new_comp["value"] = new_value
            d.setdefault("components", []).append(new_comp)
            # 复制样板在各网络中的连接，指向新元件
            for net in d.get("nets", []):
                add_conns = [{"ref": new_ref, "pin": x.get("pin")}
                             for x in net.get("connections", []) if x.get("ref") == sample.get("ref")]
                net.setdefault("connections", []).extend(add_conns)
            for g in d.get("groups", []):
                if sample.get("ref") in g.get("refs", []):
                    g.setdefault("refs", []).append(new_ref)
                    break
            changes.append("增加元件 %s=%s（%s，参照 %s 接线）" % (new_ref, new_value, cat, sample.get("ref")))

    # 4) 修改参数值
    elif new_value:
        targets, how = _find_targets(d, analysis, new_value)
        if targets:
            for c in targets:
                old = c.get("value", "")
                c["value"] = new_value
                changes.append("%s：%s → %s" % (c.get("ref"), old, new_value))
            changes.append("定位方式：" + how)

    # 5) 纯改名 / 只改难度风格这类无参数指令
    if not changes:
        # 尝试识别「把 X 的 Y 改成 Z」但 Z 无单位的情况
        m = re.search(r"(?:换成|改为|改成|设为|调整为)\s*([^\s，。,\.]{1,20})\s*$", instruction)
        if m and not re.fullmatch(r"[\d.]+\s*\w*", m.group(1)):
            targets, how = _find_targets(d, analysis, "")
            if targets:
                for c in targets:
                    old = c.get("value", "")
                    c["value"] = m.group(1)
                    changes.append("%s：%s → %s" % (c.get("ref"), old, m.group(1)))
        if not changes:
            changes.append("未能解析出明确的参数改动，已保留原设计（可试试「把 C1 换成 100nF」）")

    return validate_design(d), changes


def apply_revision(design: dict, instruction: str, analysis: dict = None, context: str = ""):
    """对话式实时修改。返回 (new_design, mode, changes)

    LLM 可用时优先让模型重写完整 JSON；失败 / 无 LLM / 内网环境下自动走离线规则引擎，
    保证「任何环境都能改图」。
    """
    if analysis is None:
        analysis = nlu.analyze(instruction, has_design=True)
    client = LLMClient()

    if client.available:
        try:
            current = json.dumps(design, ensure_ascii=False, indent=2)
            hint = nlu.to_prompt_hint(analysis)
            content = client.chat(
                [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": (
                        "当前电路设计 JSON：\n" + current + "\n\n"
                        + hint + "\n\n"
                        "修改指令：\n" + instruction + "\n\n"
                        + (("会话上下文：" + context + "\n\n") if context else "")
                        + "请根据修改指令，输出修改后的【完整】电路设计 JSON（保持原有结构，"
                          "只做指令要求的改动，其它元件和连接保持不变）：\n"
                    )},
                ],
                temperature=0.1,
                json_mode=True,
            )
            new_design = validate_design(extract_json(content))
            return new_design, f"llm:{client.mode}", ["由大模型重写完整设计 JSON"]
        except (LLMError, DesignError):
            pass  # 落到离线引擎

    new_design, changes = _apply_offline_revision(design, instruction, analysis)
    return new_design, "offline-rule", changes


# ---------------------------------------------------------------------------
# 关键词（兼容旧接口，内部升级为 NLU 归一化词表）
# ---------------------------------------------------------------------------
def extract_keywords(requirement: str):
    """从需求文本中提取电路关键词（供前端展示为 chips）"""
    return nlu.keyword_terms(nlu.analyze(requirement))


# ---------------------------------------------------------------------------
# 工程文件生成
# ---------------------------------------------------------------------------
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
