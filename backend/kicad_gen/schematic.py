# -*- coding: utf-8 -*-
"""
JSON 电路描述 → KiCad 原理图 (.kicad_sch)

采用「网络标签连接、零导线」方案（与 KiCad 实测约束一致）：
  - 每个引脚旁放置与其网络同名的 net label，同名 label 即电气相连
  - 不画任何 wire/junction，避免连线错误
  - power 符号（GND/VCC）不实例化，电源网络同样用 label 表达

输出为 KiCad 8 兼容的 s-expression 格式（version 20231120），
KiCad 8/9/10 均可直接打开。
"""

from __future__ import annotations

import uuid
import math

from .symbols import get_symbol, SYMBOL_LIB

GRID = 1.27  # 50mil 连接网格
KICAD_SCH_VERSION = 20231120


def _u():
    return str(uuid.uuid4())


def snap(v):
    """对齐到 1.27mm 网格"""
    return round(round(v / GRID) * GRID, 3)


def _fmt(v):
    """格式化浮点数：去掉多余小数点"""
    if isinstance(v, (int, float)):
        if abs(v - round(v)) < 1e-9:
            return str(int(round(v)))
        return f"{v:.3f}".rstrip("0").rstrip(".")
    return str(v)


# ---------------------------------------------------------------------------
# 符号实例相关
# ---------------------------------------------------------------------------
def pin_world(comp_x, comp_y, rot, px, py):
    """符号局部坐标 (px,py) → 原理图世界坐标。局部 y 向上、原理图 y 向下，需翻转。"""
    # 仅支持 rotation=0 的简单情形（符号均已水平定义）
    rad = math.radians(rot)
    cos, sin = math.cos(rad), math.sin(rad)
    dy = -py  # 局部 y 翻转
    wx = px * cos + dy * sin
    wy = -px * sin + dy * cos
    return snap(comp_x + wx), snap(comp_y + wy)


def symbol_bbox(sym):
    """估算符号包围盒（宽、高），用于布局"""
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
# s-expression 生成
# ---------------------------------------------------------------------------
def _pin_s(pin):
    num, name, etype, px, py, angle, length = pin
    return (
        f'        (pin {etype} line (at {_fmt(px)} {_fmt(py)} {angle}) '
        f'(length {_fmt(length)}) '
        f'(name "{name}" (effects (font (size 1.27 1.27)))) '
        f'(number "{num}" (effects (font (size 1.27 1.27)))))\n'
    )


def _graphics_s(g):
    kind = g[0]
    if kind == "rect":
        _, x1, y1, x2, y2 = g
        return (f'      (rectangle (start {_fmt(x1)} {_fmt(y1)}) '
                f'(end {_fmt(x2)} {_fmt(y2)}) '
                f'(stroke (width 0.254) (type default)) (fill (type none)))\n')
    if kind == "line":
        pts = " ".join(f"{_fmt(x)} {_fmt(y)}" for (x, y) in g[1])
        return (f'      (polyline (pts (xy {pts})) '
                f'(stroke (width 0.254) (type default)) (fill (type none)))\n')
    return ""


def _lib_symbol_s(lib_id, sym):
    """生成 lib_symbols 中的一个 symbol 定义"""
    s = f'    (symbol "{lib_id}" (pin_numbers hide) (pin_names (offset 0.254)) (in_bom yes) (on_board yes)\n'
    s += '      (property "Reference" "U" (at 0 1.27 0) (effects (font (size 1.27 1.27))))\n'
    s += '      (property "Value" "VAL" (at 0 -1.27 0) (effects (font (size 1.27 1.27))))\n'
    s += '      (property "Footprint" "" (at 0 0 0) (effects (font (size 1.27 1.27)) hide))\n'
    s += '      (property "Datasheet" "" (at 0 0 0) (effects (font (size 1.27 1.27)) hide))\n'
    # 图形 + 引脚
    inner = "".join(_graphics_s(g) for g in sym["graphics"])
    inner += "".join(_pin_s(p) for p in sym["pins"])
    s += f'      (symbol "{lib_id.split(":")[1]}_0_1"\n{inner}      )\n'
    s += "    )\n"
    return s


def _symbol_instance_s(comp, cx, cy, sym):
    """生成一个 symbol 实例（含 property 与 pin 子元素）"""
    lib_id = f'{comp["lib"]}:{comp["symbol"]}'
    value = comp.get("value", "")
    footprint = comp.get("footprint", "")
    ref = comp["ref"]
    s = f'  (symbol (lib_id "{lib_id}") (at {_fmt(cx)} {_fmt(cy)} 0) (unit 1) '
    s += '(in_bom yes) (on_board yes) (fields_autoplaced yes) (uuid "{}")\n'.format(_u())
    s += f'    (property "Reference" "{ref}" (at {_fmt(cx)} {_fmt(cy + 2.54)} 0) (effects (font (size 1.27 1.27))))\n'
    s += f'    (property "Value" "{value}" (at {_fmt(cx)} {_fmt(cy - 2.54)} 0) (effects (font (size 1.27 1.27))))\n'
    s += f'    (property "Footprint" "{footprint}" (at {_fmt(cx)} {_fmt(cy)} 0) (effects (font (size 1.27 1.27)) hide))\n'
    s += '    (property "Datasheet" "" (at {} {} 0) (effects (font (size 1.27 1.27)) hide))\n'.format(_fmt(cx), _fmt(cy))
    for p in sym["pins"]:
        s += f'    (pin "{p[0]}" (uuid "{_u()}"))\n'
    s += "  )\n"
    return s


def _label_s(name, x, y):
    return (f'  (label "{name}" (at {_fmt(x)} {_fmt(y)} 0) '
            f'(effects (font (size 1.27 1.27)) (justify left bottom)) (uuid "{_u()}"))\n')


def _module_rect_s(x1, y1, x2, y2, name, lx, ly):
    """模块虚线边框 + 模块名"""
    s = (f'  (rectangle (start {_fmt(x1)} {_fmt(y1)}) (end {_fmt(x2)} {_fmt(y2)}) '
         f'(stroke (width 0.127) (type dash)) (fill (type none)) (uuid "{_u()}"))\n')
    s += (f'  (text "{name}" (at {_fmt(lx)} {_fmt(ly)} 0) '
          f'(effects (font (size 1.27 1.27)))) (uuid "{_u()}"))\n')
    return s


# ---------------------------------------------------------------------------
# 布局
# ---------------------------------------------------------------------------
def layout_components(design):
    """
    计算每个元件的放置坐标（模块化布局：一个模块一行，组内横排）。
    返回 {ref: (cx, cy)}
    """
    comps = {c["ref"]: c for c in design["components"]}
    groups = design.get("groups") or []

    # 构建分组映射
    ref_to_group = {}
    group_order = []
    for g in groups:
        group_order.append(g["name"])
        for r in g["refs"]:
            ref_to_group[r] = g["name"]

    # 未分组的元件归入「其他」匿名组
    ungrouped = [c["ref"] for c in design["components"] if c["ref"] not in ref_to_group]
    if ungrouped:
        group_order.append("其他")
        for r in ungrouped:
            ref_to_group[r] = "其他"

    # 按分组顺序重排组件
    ordered = []
    for gname in group_order:
        for c in design["components"]:
            if ref_to_group.get(c["ref"]) == gname:
                ordered.append(c)

    positions = {}
    MARGIN = 7.62
    ROW_GAP = 12.7
    x_start = 40.64
    y_cursor = 40.64

    for gname in group_order:
        members = [c for c in ordered if ref_to_group.get(c["ref"]) == gname]
        if not members:
            continue
        row_height = 0.0
        x = x_start
        # 先算该行最大高度
        for c in members:
            sym = get_symbol(f'{c["lib"]}:{c["symbol"]}')
            if sym is None:
                continue
            _, h = symbol_bbox(sym)
            row_height = max(row_height, h)
        # 逐元件横排
        for c in members:
            sym = get_symbol(f'{c["lib"]}:{c["symbol"]}')
            if sym is None:
                continue
            w, _ = symbol_bbox(sym)
            positions[c["ref"]] = (snap(x), snap(y_cursor))
            x += w + MARGIN
        y_cursor += row_height + ROW_GAP

    return positions, group_order, ref_to_group


# ---------------------------------------------------------------------------
# 主入口
# ---------------------------------------------------------------------------
def build_schematic(design):
    """从 design JSON 生成 .kicad_sch 文本"""
    title = design.get("title", "Untitled")
    paper = design.get("paper", "A4")

    # 1. 收集用到的符号
    used_libs = {}
    for c in design["components"]:
        lib_id = f'{c["lib"]}:{c["symbol"]}'
        sym = get_symbol(lib_id)
        if sym is None:
            raise ValueError(f"未知符号: {lib_id}")
        used_libs[lib_id] = sym

    # 2. 布局
    positions, group_order, ref_to_group = layout_components(design)

    # 3. 生成 lib_symbols
    libs_s = "".join(_lib_symbol_s(lid, sym) for lid, sym in used_libs.items())

    # 4. 生成 symbol 实例
    insts_s = ""
    for c in design["components"]:
        sym = get_symbol(f'{c["lib"]}:{c["symbol"]}')
        cx, cy = positions[c["ref"]]
        insts_s += _symbol_instance_s(c, cx, cy, sym)

    # 5. 生成网络标签
    labels_s = ""
    for net in design.get("nets", []):
        name = net["name"]
        for conn in net.get("connections", []):
            ref = conn["ref"]
            pin_no = str(conn["pin"])
            c = next((x for x in design["components"] if x["ref"] == ref), None)
            if c is None:
                continue
            sym = get_symbol(f'{c["lib"]}:{c["symbol"]}')
            pin = next((p for p in sym["pins"] if p[0] == pin_no), None)
            if pin is None:
                continue
            cx, cy = positions[ref]
            wx, wy = pin_world(cx, cy, 0, pin[3], pin[4])
            labels_s += _label_s(name, wx, wy)

    # 6. 模块边框（虚线框 + 名称）
    module_s = _draw_modules(design, positions, group_order, ref_to_group)

    # 组装
    sch = f"""(kicad_sch
  (version {KICAD_SCH_VERSION})
  (generator "eda-agent")
  (generator_version "1.0")
  (uuid "{_u()}")
  (paper "{paper}")
  (lib_symbols
{libs_s}  )

{insts_s}
{labels_s}
{module_s}
  (sheet_instances
    (path "/" (page "1"))
  )
)
"""
    return sch


def _draw_modules(design, positions, group_order, ref_to_group):
    """绘制模块虚线边框"""
    out = ""
    comp_by_ref = {c["ref"]: c for c in design["components"]}
    for gname in group_order:
        members = [r for r in comp_by_ref if ref_to_group.get(r) == gname]
        if not members:
            continue
        # 计算边界
        minx = min(positions[r][0] for r in members)
        maxx = max(positions[r][0] for r in members)
        miny = min(positions[r][1] for r in members)
        maxy = max(positions[r][1] for r in members)
        pad = 6.35
        x1, y1 = snap(minx - pad), snap(miny - pad)
        x2, y2 = snap(maxx + pad), snap(maxy + pad)
        out += _module_rect_s(x1, y1, x2, y2, gname, x1 + 2.54, y1 - 2.54)
    return out
