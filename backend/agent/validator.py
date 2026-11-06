# -*- coding: utf-8 -*-
"""设计 JSON 校验与规范化

LLM 输出不可完全信任，这里做一次「工程化兜底」：
  - 校验元件编号唯一、符号存在、引脚号合法
  - 过滤无效连接、修正常见错误
  - 未通过则抛出带说明的异常，供上层反馈给用户重试
"""

from __future__ import annotations

from ..kicad_gen.symbols import get_symbol


class DesignError(Exception):
    pass


def validate_design(design: dict) -> dict:
    """校验并返回规范化后的设计 JSON"""
    if not isinstance(design, dict):
        raise DesignError("设计结果不是 JSON 对象")

    components = design.get("components") or []
    nets = design.get("nets") or []

    if not components:
        raise DesignError("元件清单为空，无法生成电路")

    # 1. 校验元件
    refs = set()
    for c in components:
        ref = c.get("ref")
        if not ref:
            raise DesignError("存在缺少 ref 的元件")
        if ref in refs:
            raise DesignError(f"元件编号重复: {ref}")
        refs.add(ref)
        lib = c.get("lib", "")
        symbol = c.get("symbol", "")
        lib_id = f"{lib}:{symbol}"
        sym = get_symbol(lib_id)
        if sym is None:
            raise DesignError(f"未知符号: {lib_id}（元件 {ref}）")
        c["lib_id"] = lib_id  # 冗余字段，方便后续

    # 2. 校验网络
    valid_pins = {}
    for c in components:
        sym = get_symbol(c["lib_id"])
        valid_pins[c["ref"]] = {str(p[0]) for p in sym["pins"]}

    cleaned_nets = []
    seen_nets = set()
    for net in nets:
        name = (net.get("name") or "").strip().upper().replace(" ", "_")
        if not name or name in seen_nets:
            continue
        seen_nets.add(name)
        conns = []
        for conn in net.get("connections", []):
            ref = conn.get("ref")
            pin = str(conn.get("pin", ""))
            if ref not in valid_pins:
                continue
            if pin not in valid_pins[ref]:
                raise DesignError(f"引脚无效: {ref}.{pin}（元件 {ref} 没有该引脚）")
            conns.append({"ref": ref, "pin": pin})
        if conns:
            cleaned_nets.append({"name": name, "connections": conns})

    design["nets"] = cleaned_nets

    # 3. 校验分组，未分组元件自动归入「其他」
    grouped = set()
    for g in design.get("groups", []):
        for r in g.get("refs", []):
            grouped.add(r)
    leftover = [r for r in refs if r not in grouped]
    if leftover:
        design.setdefault("groups", []).append({"name": "其他", "refs": leftover})

    return design
