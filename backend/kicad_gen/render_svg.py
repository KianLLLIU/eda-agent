# -*- coding: utf-8 -*-
"""
设计 JSON → 实时构图 SVG（v2.0.3 重绘版）

相比旧版解决的问题：
  · 挤在一起  → 统一 slot 网格布局，模块独占成块，卡片内含 ref/value 标签空间
  · 缺线少线  → 单引脚网络不再跳过；每条网络一条独立 lane，
                 引脚 stub → 垂直支线 → 水平主干，全部正交且不穿过元件
  · 不好看    → 标题栏 / 点阵网格 / 圆角元件卡片 / 彩色网络标签 / 图例，
                 样式全部内嵌在 SVG 里，单独下载打开也是完整的一张图

前端动画依赖的 class（.comp / .group / .net）与 data-i 均保留，
playSvgAnimation() 里的 getTotalLength() 对 <path> 同样有效。
"""

from __future__ import annotations

import html

from .symbols import get_symbol
from .layout import compute_layout, pin_world, symbol_bbox, _fmt

# 电路板风格主题
STYLE_THEMES = {
    "classic": {
        "name": "经典绿",
        "board": "#F1F7F3", "comp_fill": "#FFFFFF", "comp_stroke": "#0B3D26",
        "trace": "#1A9E5C", "pin": "#0B3D26", "label": "#123A28",
        "group": "#1A9E5C", "accent": "#0E7A46",
        "grid": "#D8E8DE", "title_bg": "#0E7A46", "title_text": "#FFFFFF",
        "sub_text": "#C9E8D7", "card_edge": "#D6E6DC", "muted": "#6B8578",
        "net_colors": ["#1A9E5C", "#2F74B5", "#C2792C", "#8B5CB7",
                       "#C05555", "#2E8B8B", "#7A7A2E", "#B0527A"],
    },
    "minimal": {
        "name": "现代极简",
        "board": "#F8F8FA", "comp_fill": "#FFFFFF", "comp_stroke": "#1F1F1F",
        "trace": "#555555", "pin": "#1F1F1F", "label": "#1F1F1F",
        "group": "#9A9AA5", "accent": "#3B3B3B",
        "grid": "#E5E5EA", "title_bg": "#22242A", "title_text": "#FFFFFF",
        "sub_text": "#B9BCC5", "card_edge": "#E3E3E8", "muted": "#7C7C86",
        "net_colors": ["#3B3B3B", "#4A6FA5", "#8A6D3B", "#7A5AA8",
                       "#A85353", "#3E7E7E", "#6B6B33", "#9A4E72"],
    },
    "retro": {
        "name": "复古暖铜",
        "board": "#FBF4E9", "comp_fill": "#FFFDF8", "comp_stroke": "#7A4A22",
        "trace": "#C0843C", "pin": "#7A4A22", "label": "#5A3A18",
        "group": "#C0843C", "accent": "#B8722C",
        "grid": "#EBDCC6", "title_bg": "#7A4A22", "title_text": "#FFF6E8",
        "sub_text": "#E7CBA7", "card_edge": "#E8D7BC", "muted": "#9A7A58",
        "net_colors": ["#C0843C", "#4E7FA0", "#8B6B3E", "#9A5E8B",
                       "#B35C4A", "#4E8B72", "#8A7A3A", "#A85C6E"],
    },
}

DEFAULT_STYLE = "classic"


def _esc(s):
    return html.escape(str(s if s is not None else ""), quote=True)


def _n(v):
    return _fmt(round(float(v), 2))


# ---------------------------------------------------------------------------
# 元件与引脚
# ---------------------------------------------------------------------------
def _render_graphics(g, cx, cy):
    """符号图形原语 → SVG（局部 y 翻转）"""
    if g[0] == "rect":
        _, x1, y1, x2, y2 = g
        x = cx + min(x1, x2)
        y = cy - max(y1, y2)
        return (f'<rect x="{_n(x)}" y="{_n(y)}" width="{_n(abs(x2 - x1))}" '
                f'height="{_n(abs(y2 - y1))}" class="body"/>')
    if g[0] == "line":
        world = [(cx + px, cy - py) for (px, py) in g[1]]
        pts = " ".join(f"{_n(x)},{_n(y)}" for x, y in world)
        return f'<polyline points="{pts}" class="body-line"/>'
    return ""


def _render_pin(pin, cx, cy):
    num, name, etype, px, py, angle, length = pin
    wx, wy = pin_world(cx, cy, 0, px, py)
    dot = f'<circle cx="{_n(wx)}" cy="{_n(wy)}" r="0.62" class="pin"/>'
    dx, dy = cx - wx, cy - wy
    d = (dx * dx + dy * dy) ** 0.5
    line = ""
    if d > 0.1:
        ux, uy = dx / d, dy / d
        ex, ey = wx + ux * 1.9, wy + uy * 1.9
        line = (f'<line x1="{_n(wx)}" y1="{_n(wy)}" x2="{_n(ex)}" y2="{_n(ey)}" '
                f'class="pin-line"/>')
    return line + dot


def _render_component(comp, cx, cy, sym, cell, idx):
    """元件卡片：圆角矩形 + 符号图形 + 引脚 + ref/value"""
    w, h = cell
    x, y = cx - w / 2, cy - h / 2
    g = "".join(_render_graphics(gr, cx, cy) for gr in sym["graphics"])
    pins = "".join(_render_pin(p, cx, cy) for p in sym["pins"])
    ref = _esc(comp.get("ref", ""))
    value = _esc(comp.get("value", ""))
    # 长文本按卡片宽度粗略截断，避免溢出卡片
    max_chars = max(8, int(w / 1.05))
    value_disp = value if len(value) <= max_chars else value[:max_chars - 1] + "…"
    return (
        f'<g class="comp" data-i="{idx}">'
        f'<rect x="{_n(x)}" y="{_n(y)}" width="{_n(w)}" height="{_n(h)}" rx="1.8" class="card"/>'
        f'{g}{pins}'
        f'<text x="{_n(cx)}" y="{_n(y + 3.6)}" class="label ref" text-anchor="middle">{ref}</text>'
        f'<text x="{_n(cx)}" y="{_n(y + h - 1.8)}" class="label value" text-anchor="middle">{value_disp}</text>'
        f'<title>{ref} = {value}</title>'
        f'</g>'
    )


# ---------------------------------------------------------------------------
# 网络：正交走线（stub → 垂直支线 → 水平主干）
# ---------------------------------------------------------------------------
def _render_net(name, pts, lane_y, color, idx):
    """返回 (path, nodes, label)。单引脚网络照样有线，绝不跳过。"""
    if not pts:
        return "", "", ""
    segs = []
    for p in pts:
        x, y, sx = p["x"], p["y"], p["stub_x"]
        segs.append(f"M {_n(x)} {_n(y)} L {_n(sx)} {_n(y)} L {_n(sx)} {_n(lane_y)}")
    xs = [p["stub_x"] for p in pts]
    left, right = min(xs), max(xs)
    if len(xs) >= 2 and right - left > 0.4:
        segs.append(f"M {_n(left)} {_n(lane_y)} L {_n(right)} {_n(lane_y)}")
    else:
        # 单引脚（或引脚 x 重合）：画一小段主干，保证有可见端点
        left, right = left - 2.6, right + 2.6
        segs.append(f"M {_n(left)} {_n(lane_y)} L {_n(right)} {_n(lane_y)}")

    # 用行内 style 指定颜色：前端 styles.css 里有 `.schematic-svg .net { stroke: var(--trace) }`，
    # CSS 规则会覆盖 presentation attribute，必须用 inline style 才能保留每条网络的独立配色。
    path = (f'<path class="net" data-i="{idx}" data-net="{_esc(name)}" '
            f'd="{" ".join(segs)}" style="stroke:{color}"/>')

    nodes = "".join(
        f'<circle cx="{_n(p["x"])}" cy="{_n(p["y"])}" r="0.9" fill="{color}" class="net-pin"/>'
        for p in pts
    )
    nodes += (f'<circle cx="{_n(left)}" cy="{_n(lane_y)}" r="0.85" fill="{color}" class="net-node"/>'
              f'<circle cx="{_n(right)}" cy="{_n(lane_y)}" r="0.85" fill="{color}" class="net-node"/>')

    # 网络名药丸：放在主干中部上方，不遮挡线
    label = _esc(name)
    pill_w = max(6.0, len(label) * 1.35 + 3.2)
    mid = (left + right) / 2
    pill_x = mid - pill_w / 2
    pill_y = lane_y - 3.35
    tag = (
        f'<g class="net-label" data-i="{idx}">'
        f'<rect x="{_n(pill_x)}" y="{_n(pill_y)}" width="{_n(pill_w)}" height="3.3" '
        f'rx="1.65" fill="{color}"/>'
        f'<text x="{_n(mid)}" y="{_n(pill_y + 2.35)}" class="net-text" '
        f'text-anchor="middle">{label}</text></g>'
    )
    return path, nodes + tag, ""


# ---------------------------------------------------------------------------
# 主入口
# ---------------------------------------------------------------------------
def build_svg(design, style="classic"):
    """design JSON → 自包含 SVG 字符串（含动画序号）"""
    theme = STYLE_THEMES.get(style, STYLE_THEMES[DEFAULT_STYLE])
    lay = compute_layout(design)
    x0, y0, x1, y1 = lay["bounds"]
    W, H = x1 - x0, y1 - y0
    colors = theme["net_colors"]
    stats = lay["stats"]
    comps_by_ref = {c["ref"]: c for c in design.get("components", [])}

    parts = []

    # 1. 标题栏
    parts.append(
        f'<g class="titlebar">'
        f'<rect x="0" y="0" width="{_n(W)}" height="34" fill="{theme["title_bg"]}"/>'
        f'<circle cx="13" cy="17" r="5.2" fill="none" stroke="{theme["title_text"]}" stroke-width="1.2" opacity="0.9"/>'
        f'<path d="M 10.4 17 h 5.2 M 13 14.4 v 5.2" stroke="{theme["title_text"]}" stroke-width="1.1"/>'
        f'<text x="25" y="15.5" class="title-text">{_esc(lay["title"])}</text>'
        f'<text x="25" y="26" class="title-sub">{stats["components"]} 元件 · {stats["nets"]} 网络 · '
        f'{stats["connections"]} 连接点 · {stats["groups"]} 模块 · {_esc(theme["name"])}</text>'
        f'<text x="{_n(W - 12)}" y="21" class="title-brand" text-anchor="end">EDA AGENT</text>'
        f'</g>'
    )

    # 2. 模块分组框
    for gi, gname in enumerate(lay["group_order"]):
        box = lay["group_boxes"].get(gname)
        if not box:
            continue
        bx1, by1, bx2, by2 = box
        parts.append(
            f'<g class="group" data-i="{gi}">'
            f'<rect x="{_n(bx1)}" y="{_n(by1)}" width="{_n(bx2 - bx1)}" height="{_n(by2 - by1)}" '
            f'rx="3" class="group-box"/>'
            f'<rect x="{_n(bx1 + 1.5)}" y="{_n(by1 + 1.4)}" width="{_n(max(9, len(gname) * 2.1 + 4))}" '
            f'height="5.2" rx="1.4" class="group-tag"/>'
            f'<text x="{_n(bx1 + 3.5)}" y="{_n(by1 + 5.1)}" class="group-name">{_esc(gname)}</text>'
            f'</g>'
        )

    # 3. 网络连线（先画，元件覆盖其上）
    idx = len(lay["group_order"])
    net_paths, net_marks = [], []
    for ni, (name, pts) in enumerate(lay["net_points"].items()):
        color = colors[ni % len(colors)]
        lane_y = lay["lanes"][name]
        p, marks, _ = _render_net(name, pts, lane_y, color, idx)
        if p:
            net_paths.append(p)
            net_marks.append(marks)
            idx += 1
    parts.extend(net_paths)
    parts.extend(net_marks)

    # 4. 元件
    for comp in design.get("components", []):
        ref = comp["ref"]
        if ref not in lay["positions"]:
            continue
        sym = get_symbol(f'{comp["lib"]}:{comp["symbol"]}')
        if sym is None:
            continue
        cx, cy = lay["positions"][ref]
        parts.append(_render_component(comp, cx, cy, sym, lay["cells"][ref], idx))
        idx += 1

    # 5. 底部图例
    fy = lay["lane_bottom"] + 9
    parts.append(
        f'<g class="footer">'
        f'<line x1="12" y1="{_n(fy - 3)}" x2="{_n(W - 12)}" y2="{_n(fy - 3)}" class="footer-line"/>'
        f'<circle cx="16" cy="{_n(fy + 2)}" r="0.85" fill="{colors[0]}"/>'
        f'<text x="20" y="{_n(fy + 3)}" class="footer-text">每条彩色线 = 一条电气网络；'
        f'圆点为引脚，同色线相连即导通</text>'
        f'<text x="{_n(W - 12)}" y="{_n(fy + 3)}" class="footer-text" text-anchor="end">'
        f'EDA Agent · 自动构图</text>'
        f'</g>'
    )

    inner = "\n  ".join(parts)
    css = f"""
    .schematic-svg {{ font-family: 'Segoe UI','PingFang SC','Microsoft YaHei',sans-serif; }}
    .schematic-svg .board {{ fill: {theme['board']}; }}
    .schematic-svg .card {{ fill: {theme['comp_fill']}; stroke: {theme['card_edge']}; stroke-width: 0.35; }}
    .schematic-svg .body {{ fill: none; stroke: {theme['comp_stroke']}; stroke-width: 0.45; }}
    .schematic-svg .body-line {{ fill: none; stroke: {theme['comp_stroke']}; stroke-width: 0.45; stroke-linecap: round; stroke-linejoin: round; }}
    .schematic-svg .pin {{ fill: {theme['pin']}; }}
    .schematic-svg .pin-line {{ stroke: {theme['pin']}; stroke-width: 0.4; }}
    .schematic-svg .label {{ fill: {theme['label']}; font-size: 2.9px; }}
    .schematic-svg .label.ref {{ font-weight: 700; font-size: 3.05px; }}
    .schematic-svg .label.value {{ fill: {theme['muted']}; font-size: 2.6px; }}
    .schematic-svg .net {{ fill: none; stroke-width: 0.55; stroke-linecap: round; stroke-linejoin: round; opacity: 0.9; }}
    .schematic-svg .net-text {{ fill: #FFFFFF; font-size: 2.35px; font-weight: 700; letter-spacing: 0.05px; }}
    .schematic-svg .group-box {{ fill: none; stroke: {theme['group']}; stroke-width: 0.3; stroke-dasharray: 1.6 1.3; opacity: 0.72; }}
    .schematic-svg .group-tag {{ fill: {theme['group']}; opacity: 0.16; }}
    .schematic-svg .group-name {{ fill: {theme['accent']}; font-size: 2.8px; font-weight: 700; }}
    .schematic-svg .title-text {{ fill: {theme['title_text']}; font-size: 6.2px; font-weight: 700; }}
    .schematic-svg .title-sub {{ fill: {theme['sub_text']}; font-size: 2.9px; }}
    .schematic-svg .title-brand {{ fill: {theme['title_text']}; font-size: 3.1px; font-weight: 700; letter-spacing: 0.7px; opacity: 0.85; }}
    .schematic-svg .footer-line {{ stroke: {theme['card_edge']}; stroke-width: 0.3; }}
    .schematic-svg .footer-text {{ fill: {theme['muted']}; font-size: 2.5px; }}
    """

    svg = f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="{_n(x0)} {_n(y0)} {_n(W)} {_n(H)}" class="schematic-svg" preserveAspectRatio="xMidYMid meet">
  <style>{css}</style>
  <defs>
    <pattern id="dotgrid" width="5" height="5" patternUnits="userSpaceOnUse">
      <circle cx="0.6" cy="0.6" r="0.32" fill="{theme['grid']}"/>
    </pattern>
  </defs>
  <rect x="{_n(x0)}" y="{_n(y0)}" width="{_n(W)}" height="{_n(H)}" class="board"/>
  <rect x="{_n(x0)}" y="34" width="{_n(W)}" height="{_n(max(0, H - 34))}" fill="url(#dotgrid)" opacity="0.65"/>
  {inner}
</svg>'''
    return svg


def get_theme(style="classic"):
    """返回风格主题（供前端 accent 色等使用）"""
    return STYLE_THEMES.get(style, STYLE_THEMES[DEFAULT_STYLE])
