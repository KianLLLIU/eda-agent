# -*- coding: utf-8 -*-
"""
JSON 电路描述 → KiCad 原理图 (.kicad_sch)

v2.0.4 重做：从「零导线 + 每个引脚一个标签」改为「真实导线连接」。

旧版问题（用户反馈「连线丢失、挤成一坨、图不清楚」）：
  · 整个文件 wire=0 / junction=0，只有网络标签，KiCad 里自然看不到任何连线；
  · 每个引脚都放一个同名 label，13 个连接 → 13 个文字挤在几十毫米内互相重叠；
  · Reference/Value 固定放在 cy±2.54，大符号（ATmega328P 高约 71mm）会压在图形中间。

现在的方案：
  · 每条网络：引脚 → 水平 stub → 垂直支线 → 水平主干，全部真实 (wire)，
    T 型交点加 (junction)，主干上只放 1 个 (label) 命名该网络；
  · 主干通道由统一布局引擎分配在元件区下方，x 区间不重叠的网络复用通道；
  · 元件属性按符号包围盒放到图形外侧，模块框用布局引擎算好的不重叠矩形；
  · 纸张按内容范围自动选 A4 / A3 / A2，避免内容跑出页面。

格式仍为 KiCad 8 兼容的 s-expression（version 20231120），
已用 KiCad 10.0.7 的 kicad-cli（export svg + erc）实测。
"""

from __future__ import annotations

import math
import uuid

from .symbols import get_symbol

GRID = 1.27
KICAD_SCH_VERSION = 20231120


def _u():
    return str(uuid.uuid4())


def snap(v):
    """对齐到 1.27mm 网格（KiCad wire 端点必须落在网格上）"""
    return round(round(v / GRID) * GRID, 3)


def _fmt(v):
    if isinstance(v, (int, float)):
        if abs(v - round(v)) < 1e-9:
            return str(int(round(v)))
        return f"{v:.3f}".rstrip("0").rstrip(".")
    return str(v)


def _esc(s):
    return str(s if s is not None else "").replace("\\", "\\\\").replace('"', '\\"')


# ---------------------------------------------------------------------------
# 坐标与包围盒
# ---------------------------------------------------------------------------
def pin_world(comp_x, comp_y, rot, px, py):
    """符号局部坐标 → 画布世界坐标（局部 y 向上、原理图 y 向下）"""
    rad = math.radians(rot)
    cos, sin = math.cos(rad), math.sin(rad)
    dy = -py
    wx = px * cos + dy * sin
    wy = -px * sin + dy * cos
    return snap(comp_x + wx), snap(comp_y + wy)


def symbol_bbox(sym):
    """估算符号包围盒（宽、高），包含所有引脚与图形"""
    maxx = maxy = 0.0
    for (_, _, _, px, py, _, _) in sym["pins"]:
        maxx = max(maxx, abs(px))
        maxy = max(maxy, abs(py))
    for g in sym["graphics"]:
        if g[0] == "rect":
            _, x1, y1, x2, y2 = g
            maxx = max(maxx, abs(x1), abs(x2))
            maxy = max(maxy, abs(y1), abs(y2))
        elif g[0] == "line":
            for (x, y) in g[1]:
                maxx = max(maxx, abs(x))
                maxy = max(maxy, abs(y))
    return maxx * 2 + 2.54, maxy * 2 + 2.54


# ---------------------------------------------------------------------------
# s-expression 片段
# ---------------------------------------------------------------------------
def _pin_s(pin):
    num, name, etype, px, py, angle, length = pin
    return (
        f'        (pin {etype} line (at {_fmt(px)} {_fmt(py)} {angle}) '
        f'(length {_fmt(length)}) '
        f'(name "{_esc(name)}" (effects (font (size 1.27 1.27)))) '
        f'(number "{_esc(num)}" (effects (font (size 1.27 1.27)))))\n'
    )


def _graphics_s(g):
    kind = g[0]
    if kind == "rect":
        _, x1, y1, x2, y2 = g
        return (f'      (rectangle (start {_fmt(x1)} {_fmt(y1)}) '
                f'(end {_fmt(x2)} {_fmt(y2)}) '
                f'(stroke (width 0.254) (type default)) (fill (type none)))\n')
    if kind == "line":
        pts = " ".join(f"(xy {_fmt(x)} {_fmt(y)})" for (x, y) in g[1])
        return (f'      (polyline (pts {pts}) '
                f'(stroke (width 0.254) (type default)) (fill (type none)))\n')
    return ""


def _lib_symbol_s(lib_id, sym):
    s = f'    (symbol "{lib_id}" (pin_numbers hide) (pin_names (offset 0.254)) (in_bom yes) (on_board yes)\n'
    s += '      (property "Reference" "U" (at 0 1.27 0) (effects (font (size 1.27 1.27))))\n'
    s += '      (property "Value" "VAL" (at 0 -1.27 0) (effects (font (size 1.27 1.27))))\n'
    s += '      (property "Footprint" "" (at 0 0 0) (effects (font (size 1.27 1.27)) hide))\n'
    s += '      (property "Datasheet" "" (at 0 0 0) (effects (font (size 1.27 1.27)) hide))\n'
    inner = "".join(_graphics_s(g) for g in sym["graphics"])
    inner += "".join(_pin_s(p) for p in sym["pins"])
    s += f'      (symbol "{_esc(lib_id.split(":")[1])}_0_1"\n{inner}      )\n'
    s += "    )\n"
    return s


def _symbol_instance_s(comp, cx, cy, sym):
    """元件实例；Reference/Value 放到符号包围盒外侧，不再压在图形上。"""
    lib_id = f'{comp["lib"]}:{comp["symbol"]}'
    value = _esc(comp.get("value", ""))
    footprint = _esc(comp.get("footprint", ""))
    ref = _esc(comp["ref"])
    _, h = symbol_bbox(sym)
    ref_y = snap(cy - h / 2 - 1.27)      # 符号上方
    value_y = snap(cy + h / 2 + 2.54)    # 符号下方

    s = f'  (symbol (lib_id "{_esc(lib_id)}") (at {_fmt(cx)} {_fmt(cy)} 0) (unit 1) '
    s += '(in_bom yes) (on_board yes) (fields_autoplaced yes) (uuid "{}")\n'.format(_u())
    s += f'    (property "Reference" "{ref}" (at {_fmt(cx)} {_fmt(ref_y)} 0) (effects (font (size 1.27 1.27))))\n'
    s += f'    (property "Value" "{value}" (at {_fmt(cx)} {_fmt(value_y)} 0) (effects (font (size 1.27 1.27))))\n'
    s += f'    (property "Footprint" "{footprint}" (at {_fmt(cx)} {_fmt(cy)} 0) (effects (font (size 1.27 1.27)) hide))\n'
    s += f'    (property "Datasheet" "" (at {_fmt(cx)} {_fmt(cy)} 0) (effects (font (size 1.27 1.27)) hide))\n'
    for p in sym["pins"]:
        s += f'    (pin "{_esc(p[0])}" (uuid "{_u()}"))\n'
    s += "  )\n"
    return s


def _wire_s(x1, y1, x2, y2):
    """一段真实导线（KiCad 9/10 格式）"""
    if abs(x1 - x2) < 1e-6 and abs(y1 - y2) < 1e-6:
        return ""
    return (
        "  (wire\n"
        f"    (pts (xy {_fmt(x1)} {_fmt(y1)}) (xy {_fmt(x2)} {_fmt(y2)}))\n"
        "    (stroke (width 0) (type default))\n"
        f'    (uuid "{_u()}")\n'
        "  )\n"
    )


def _junction_s(x, y):
    """T 型交点：让支线与主干在电气上真正连通"""
    return (
        "  (junction\n"
        f"    (at {_fmt(x)} {_fmt(y)})\n"
        "    (diameter 1.016)\n"
        "    (color 0 0 0 0)\n"
        f'    (uuid "{_u()}")\n'
        "  )\n"
    )


def _label_s(name, x, y):
    """一条网络只放一个标签，放在主干左端上方，避免文字堆叠"""
    return (
        f'  (label "{_esc(name)}"\n'
        f"    (at {_fmt(x)} {_fmt(y)} 0)\n"
        "    (effects (font (size 1.27 1.27)) (justify left bottom))\n"
        f'    (uuid "{_u()}")\n'
        "  )\n"
    )


def _module_rect_s(x1, y1, x2, y2, name, lx, ly):
    """模块虚线框 + 框内标题"""
    s = (f'  (rectangle (start {_fmt(x1)} {_fmt(y1)}) (end {_fmt(x2)} {_fmt(y2)}) '
         f'(stroke (width 0.127) (type dash)) (fill (type none)) (uuid "{_u()}"))\n')
    # 括号层级：(text ... (effects ...) (uuid "..."))，uuid 必须留在 text 内部
    s += (f'  (text "{_esc(name)}" (at {_fmt(lx)} {_fmt(ly)} 0) '
          f'(effects (font (size 1.27 1.27))) '
          f'(uuid "{_u()}"))\n')
    return s


# ---------------------------------------------------------------------------
# 布局（委托统一引擎，保留旧签名给外部调用）
# ---------------------------------------------------------------------------
SCH_LAYOUT = dict(max_cols=4, title_h=6, group_gap=22, lane_gap=5.08)


def layout_components(design):
    from .layout import compute_layout
    lay = compute_layout(design, **SCH_LAYOUT)
    return lay["positions"], lay["group_order"], lay["ref_to_group"]


def _pick_paper(width, height):
    """按内容范围选纸张；原理图不需要 SVG 的标题栏/页脚，按实际内容估算。"""
    if width <= 287 and height <= 200:
        return "A4"
    if width <= 410 and height <= 300:
        return "A3"
    return "A2"


# ---------------------------------------------------------------------------
# 主入口
# ---------------------------------------------------------------------------
def build_schematic(design):
    from .layout import compute_layout

    title = _esc(design.get("title", "Untitled"))
    lay = compute_layout(design, **SCH_LAYOUT)
    positions = lay["positions"]
    comps_by_ref = {c["ref"]: c for c in design.get("components", [])}

    # 1. lib_symbols
    used_libs = {}
    for c in design.get("components", []):
        lib_id = f'{c["lib"]}:{c["symbol"]}'
        sym = get_symbol(lib_id)
        if sym is None:
            raise ValueError(f"未知符号: {lib_id}")
        used_libs[lib_id] = sym
    libs_s = "".join(_lib_symbol_s(lid, sym) for lid, sym in used_libs.items())

    # 2. 元件实例
    insts_s = ""
    for c in design.get("components", []):
        if c["ref"] not in positions:
            continue
        sym = get_symbol(f'{c["lib"]}:{c["symbol"]}')
        cx, cy = positions[c["ref"]]
        insts_s += _symbol_instance_s(c, cx, cy, sym)

    # 3. 真实导线 + junction + 每网络一个标签
    wires_s, junctions_s, labels_s = "", "", ""
    for name, pts in lay["net_points"].items():
        if not pts:
            continue
        lane_y = lay["lanes"][name]
        for p in pts:
            wires_s += _wire_s(p["x"], p["y"], p["stub_x"], p["y"])      # 引脚 stub
            wires_s += _wire_s(p["stub_x"], p["y"], p["stub_x"], lane_y)  # 垂直支线

        xs = sorted(set(p["stub_x"] for p in pts))
        left, right = xs[0], xs[-1]
        if len(xs) >= 2 and right - left > 0.4:
            wires_s += _wire_s(left, lane_y, right, lane_y)               # 水平主干
            # 每个支线接入主干的位置都加 junction，保证 T 型连接被 KiCad 认可
            for x in xs:
                junctions_s += _junction_s(x, lane_y)
            label_x = left
        else:
            # 单引脚网络：竖线底端就是网络端点，label 直接贴在该点。
            # 不额外画一段主干，否则会产生悬空 wire 端点
            # （ERC: label_dangling / unconnected_wire_endpoint）。
            label_x = left
        # label 必须落在 wire 端点上才会被 KiCad 认作网络名
        labels_s += _label_s(name, label_x, lane_y)

    # 4. 未接入任何网络的引脚打 no_connect 标记：
    #    既让 ERC 不再刷屏 pin_not_connected，图上也能明确看出哪些脚是悬空的
    connected_pins = set()
    for net in design.get("nets", []) or []:
        for conn in net.get("connections", []) or []:
            connected_pins.add((conn.get("ref"), str(conn.get("pin", ""))))
    nc_s = ""
    for c in design.get("components", []):
        sym = get_symbol(f'{c["lib"]}:{c["symbol"]}')
        if sym is None or c["ref"] not in positions:
            continue
        cx, cy = positions[c["ref"]]
        for p in sym["pins"]:
            if (c["ref"], str(p[0])) in connected_pins:
                continue
            wx, wy = pin_world(cx, cy, 0, p[3], p[4])
            nc_s += f'  (no_connect (at {_fmt(wx)} {_fmt(wy)}) (uuid "{_u()}"))\n'

    # 5. 模块框（用引擎算好的不重叠矩形）
    module_s = ""
    for gname in lay["group_order"]:
        box = lay["group_boxes"].get(gname)
        if not box:
            continue
        x1, y1, x2, y2 = box
        module_s += _module_rect_s(x1, y1, x2, y2, gname, snap(x1 + 2.54), snap(y1 + 4.2))

    # 减去 SVG 专用的页脚/页边距，按原理图实际内容高度选纸
    paper = _pick_paper(lay["bounds"][2] - 14.0, lay["lane_bottom"] + 12.0)

    sch = f"""(kicad_sch
  (version {KICAD_SCH_VERSION})
  (generator "eda-agent")
  (generator_version "2.0.4")
  (uuid "{_u()}")
  (paper "{paper}")
  (title_block
    (title "{title}")
    (rev "1.0")
  )
  (lib_symbols
{libs_s}  )

{insts_s}
{wires_s}
{junctions_s}
{labels_s}
{nc_s}
{module_s}
  (sheet_instances
    (path "/" (page "1"))
  )
)
"""
    return sch


def _draw_modules(design, positions, group_order, ref_to_group):
    """兼容旧调用：改用统一布局的模块框"""
    from .layout import compute_layout
    lay = compute_layout(design, **SCH_LAYOUT)
    out = ""
    for gname in lay["group_order"]:
        box = lay["group_boxes"].get(gname)
        if not box:
            continue
        x1, y1, x2, y2 = box
        out += _module_rect_s(x1, y1, x2, y2, gname, snap(x1 + 2.54), snap(y1 + 4.2))
    return out
