# -*- coding: utf-8 -*-
"""
设计 JSON → 实时构图 SVG

把电路描述渲染成一张 SVG 原理图（元件方框 + 引脚 + 网络连线 + 模块分组），
每个元件/每条连线都带 data-i 序号，前端用 CSS 做「元件逐个出现、连线逐条画出」的
实时构图动画，让用户直观看到整块电路板的构建过程。
"""

from __future__ import annotations

from .symbols import get_symbol
from .schematic import layout_components, pin_world, symbol_bbox

# 电路板风格主题（影响 SVG 预览配色 + 前端 accent 色）
STYLE_THEMES = {
    "classic": {
        "name": "经典绿",
        "board": "#EEF6F0",
        "comp_fill": "#FFFFFF",
        "comp_stroke": "#0B3D26",
        "trace": "#1A9E5C",
        "pin": "#0B3D26",
        "label": "#0B3D26",
        "group": "#1A9E5C",
        "accent": "#0E7A46",
    },
    "minimal": {
        "name": "现代极简",
        "board": "#F6F6F8",
        "comp_fill": "#FFFFFF",
        "comp_stroke": "#1F1F1F",
        "trace": "#555555",
        "pin": "#1F1F1F",
        "label": "#1F1F1F",
        "group": "#9A9AA5",
        "accent": "#3B3B3B",
    },
    "retro": {
        "name": "复古暖铜",
        "board": "#F8F0E4",
        "comp_fill": "#FFFDF8",
        "comp_stroke": "#7A4A22",
        "trace": "#C0843C",
        "pin": "#7A4A22",
        "label": "#5A3A18",
        "group": "#C0843C",
        "accent": "#B8722C",
    },
}

DEFAULT_STYLE = "classic"


def _render_graphics(g, cx, cy):
    """符号图形原语 → SVG（局部 y 翻转：世界 y = cy - 局部 y）"""
    if g[0] == "rect":
        _, x1, y1, x2, y2 = g
        x = cx + min(x1, x2)
        y = cy - max(y1, y2)
        w = abs(x2 - x1)
        h = abs(y2 - y1)
        return f'<rect x="{x:.2f}" y="{y:.2f}" width="{w:.2f}" height="{h:.2f}" class="body"/>'
    if g[0] == "line":
        _, pts = g
        world = [(cx + px, cy - py) for (px, py) in pts]
        pts_str = " ".join(f"{x:.2f},{y:.2f}" for x, y in world)
        return f'<polyline points="{pts_str}" class="body-line"/>'
    return ""


def _render_pin(pin, cx, cy):
    """引脚点 + 往元件体内的短引脚线"""
    num, name, etype, px, py, angle, length = pin
    wx, wy = pin_world(cx, cy, 0, px, py)
    dot = f'<circle cx="{wx:.2f}" cy="{wy:.2f}" r="0.55" class="pin"/>'
    dx, dy = cx - wx, cy - wy
    d = (dx * dx + dy * dy) ** 0.5
    line = ""
    if d > 0.1:
        ux, uy = dx / d, dy / d
        ex, ey = wx + ux * 1.9, wy + uy * 1.9
        line = f'<line x1="{wx:.2f}" y1="{wy:.2f}" x2="{ex:.2f}" y2="{ey:.2f}" class="pin-line"/>'
    return dot + line


def _render_component(comp, cx, cy, sym, idx):
    """渲染单个元件"""
    g = "".join(_render_graphics(gr, cx, cy) for gr in sym["graphics"])
    pins = "".join(_render_pin(p, cx, cy) for p in sym["pins"])
    w, h = symbol_bbox(sym)
    ref = comp.get("ref", "")
    value = comp.get("value", "")
    label = (f'<text x="{cx:.2f}" y="{cy - h / 2 - 1.5:.2f}" class="label ref" text-anchor="middle">{ref}</text>'
             f'<text x="{cx:.2f}" y="{cy + h / 2 + 2.8:.2f}" class="label value" text-anchor="middle">{value}</text>')
    return f'<g class="comp" data-i="{idx}" transform="translate({0},{0})">{g}{pins}{label}</g>'


def _render_net(net, positions, comps_by_ref, idx):
    """渲染一条网络连线（折线连接所有引脚）"""
    pts = []
    for conn in net.get("connections", []):
        ref = conn.get("ref")
        pin_no = str(conn.get("pin", ""))
        comp = comps_by_ref.get(ref)
        if comp is None:
            continue
        sym = get_symbol(f'{comp["lib"]}:{comp["symbol"]}')
        if sym is None:
            continue
        pin = next((p for p in sym["pins"] if p[0] == pin_no), None)
        if pin is None or ref not in positions:
            continue
        cx, cy = positions[ref]
        wx, wy = pin_world(cx, cy, 0, pin[3], pin[4])
        pts.append((wx, wy))
    if len(pts) < 2:
        return ""
    # 折线按顺序连接；为减少交叉，按 x 排序
    pts = sorted(pts, key=lambda p: (p[0], p[1]))
    pts_str = " ".join(f"{x:.2f},{y:.2f}" for x, y in pts)
    name = net.get("name", "")
    return f'<polyline points="{pts_str}" class="net" data-i="{idx}" data-net="{name}"/>'


def build_svg(design, style="classic"):
    """design JSON → SVG 字符串（含动画序号）"""
    theme = STYLE_THEMES.get(style, STYLE_THEMES[DEFAULT_STYLE])
    positions, group_order, ref_to_group = layout_components(design)
    comps_by_ref = {c["ref"]: c for c in design["components"]}

    # 收集所有元件的边界
    xs, ys = [], []
    for ref, (cx, cy) in positions.items():
        comp = comps_by_ref.get(ref)
        if comp is None:
            continue
        sym = get_symbol(f'{comp["lib"]}:{comp["symbol"]}')
        if sym is None:
            continue
        w, h = symbol_bbox(sym)
        xs += [cx - w / 2, cx + w / 2]
        ys += [cy - h / 2, cy + h / 2]
        for pin in sym["pins"]:
            wx, wy = pin_world(cx, cy, 0, pin[3], pin[4])
            xs.append(wx)
            ys.append(wy)

    pad = 12.0
    min_x, max_x = min(xs) - pad, max(xs) + pad
    min_y, max_y = min(ys) - pad, max(ys) + pad
    vb_w, vb_h = max_x - min_x, max_y - min_y

    parts = []

    # 1. 模块分组虚线框 + 模块名
    for gi, gname in enumerate(group_order):
        members = [r for r in positions if ref_to_group.get(r) == gname]
        if not members:
            continue
        gxs, gys = [], []
        for r in members:
            comp = comps_by_ref.get(r)
            if comp is None:
                continue
            sym = get_symbol(f'{comp["lib"]}:{comp["symbol"]}')
            if sym is None:
                continue
            cx, cy = positions[r]
            w, h = symbol_bbox(sym)
            gxs += [cx - w / 2, cx + w / 2]
            gys += [cy - h / 2, cy + h / 2]
        x1, x2 = min(gxs) - 4, max(gxs) + 4
        y1, y2 = min(gys) - 3, max(gys) + 3
        parts.append(
            f'<g class="group" data-i="{gi}">'
            f'<rect x="{x1:.2f}" y="{y1:.2f}" width="{x2 - x1:.2f}" height="{y2 - y1:.2f}" class="group-box"/>'
            f'<text x="{x1 + 1.5:.2f}" y="{y1 - 1.5:.2f}" class="group-name">{gname}</text></g>'
        )

    # 2. 网络连线（先画，元件覆盖其上）
    idx = len(group_order)
    for net in design.get("nets", []):
        s = _render_net(net, positions, comps_by_ref, idx)
        if s:
            parts.append(s)
            idx += 1

    # 3. 元件（后画，覆盖连线端点）
    for comp in design["components"]:
        ref = comp["ref"]
        if ref not in positions:
            continue
        sym = get_symbol(f'{comp["lib"]}:{comp["symbol"]}')
        if sym is None:
            continue
        cx, cy = positions[ref]
        parts.append(_render_component(comp, cx, cy, sym, idx))
        idx += 1

    inner = "\n  ".join(parts)
    svg = f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="{min_x:.2f} {min_y:.2f} {vb_w:.2f} {vb_h:.2f}" class="schematic-svg" style="--board:{theme['board']};--comp:{theme['comp_fill']};--comp-stroke:{theme['comp_stroke']};--trace:{theme['trace']};--pin:{theme['pin']};--label:{theme['label']};--group:{theme['group']}">
  <rect x="{min_x:.2f}" y="{min_y:.2f}" width="{vb_w:.2f}" height="{vb_h:.2f}" class="board"/>
  {inner}
</svg>'''
    return svg


def get_theme(style="classic"):
    """返回风格主题（供前端 accent 色等使用）"""
    return STYLE_THEMES.get(style, STYLE_THEMES[DEFAULT_STYLE])
