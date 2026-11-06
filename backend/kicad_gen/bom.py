# -*- coding: utf-8 -*-
"""BOM 与网表导出（CSV / Markdown）"""

from __future__ import annotations

import csv
import io
from collections import defaultdict


def _grouped_bom(design):
    """按 (value, footprint) 归并，返回 [(value, footprint, refs, qty)]"""
    groups = defaultdict(list)
    for c in design["components"]:
        key = (c.get("value", ""), c.get("footprint", ""), c.get("lib", "") + ":" + c.get("symbol", ""))
        groups[key].append(c["ref"])
    rows = []
    for (value, fp, sym), refs in sorted(groups.items(), key=lambda x: x[0][0]):
        rows.append({"value": value, "footprint": fp, "symbol": sym, "refs": sorted(refs), "qty": len(refs)})
    return rows


def bom_csv(design):
    """生成 BOM CSV 文本"""
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(["Ref", "Qty", "Value", "Footprint", "Symbol"])
    for r in _grouped_bom(design):
        w.writerow([", ".join(r["refs"]), r["qty"], r["value"], r["footprint"], r["symbol"]])
    return out.getvalue()


def bom_markdown(design):
    """生成 BOM Markdown 表"""
    lines = ["# BOM 元器件清单", ""]
    lines.append(f"| 编号 | 数量 | 参数值 | 封装 | 符号 |")
    lines.append("|------|------|--------|------|------|")
    for r in _grouped_bom(design):
        refs = ", ".join(r["refs"])
        lines.append(f"| {refs} | {r['qty']} | {r['value']} | {r['footprint']} | {r['symbol']} |")
    lines.append("")
    lines.append(f"**合计元件数：{len(design['components'])}**")
    return "\n".join(lines)


def netlist_markdown(design):
    """生成网表连接 Markdown 表"""
    lines = ["# 网络连接表", ""]
    for net in design.get("nets", []):
        conns = net.get("connections", [])
        desc = ", ".join(f"{c['ref']}.{c['pin']}" for c in conns)
        lines.append(f"### {net['name']}")
        lines.append(f"连接：{desc}")
        lines.append("")
    return "\n".join(lines)
