# -*- coding: utf-8 -*-
"""
JSON 电路描述 → KiCad PCB (.kicad_pcb)

按 KiCad 9/10 官方格式生成（version 20241229）。v2.0.2 修复的兼容点：

  1. 顶层**不能有** (uuid ...)。KiCad 9+ 的 pcb 解析器遇到顶层 uuid 会直接报
     ``Unknown token 'uuid' ... line 5, offset 4``（KiCad 10.0.7 实测）。
     uuid 只允许出现在元素内部（footprint / property / gr_line）。
  2. 层编号改用新版（0 F.Cu / 2 B.Cu / 25 Edge.Cuts ...），旧编号是 KiCad 6~8 的。
  3. 图形用 ``(stroke (width ...) (type ...))``，不再用旧版裸 ``(width ...)``。
  4. generator / generator_version 按官方写 pcbnew / 9.0。

生成的 PCB 是一个干净的起点：板框 + 元件封装摆放 + 网络声明，
自动布线留给用户或后续进阶内容。封装通过 KiCad 全局 fp-lib-table 解析，
因此工程级 fp-lib-table 保持为空（跨 KiCad 8/9/10 都不会因环境变量名失效）。
"""

from __future__ import annotations

import uuid

PCB_VERSION = 20241229
GENERATOR_VERSION = "9.0"

# KiCad 9/10 官方 layers 块（层编号与旧版不同，必须照抄）
_LAYERS = [
    '(0 "F.Cu" signal)',
    '(2 "B.Cu" signal)',
    '(9 "F.Adhes" user "F.Adhesive")',
    '(11 "B.Adhes" user "B.Adhesive")',
    '(13 "F.Paste" user)',
    '(15 "B.Paste" user)',
    '(5 "F.SilkS" user "F.Silkscreen")',
    '(7 "B.SilkS" user "B.Silkscreen")',
    '(1 "F.Mask" user)',
    '(3 "B.Mask" user)',
    '(17 "Dwgs.User" user "User.Drawings")',
    '(19 "Cmts.User" user "User.Comments")',
    '(21 "Eco1.User" user "User.Eco1")',
    '(23 "Eco2.User" user "User.Eco2")',
    '(25 "Edge.Cuts" user)',
    '(27 "Margin" user)',
    '(31 "F.CrtYd" user "F.Courtyard")',
    '(29 "B.CrtYd" user "B.Courtyard")',
    '(35 "F.Fab" user)',
    '(33 "B.Fab" user)',
]


def _u():
    return str(uuid.uuid4())


def _fmt(v):
    if isinstance(v, (int, float)):
        if abs(v - round(v)) < 1e-9:
            return str(int(round(v)))
        return f"{v:.3f}".rstrip("0").rstrip(".")
    return str(v)


def _esc(s):
    """转义 s-expression 字符串里的引号与反斜杠"""
    return str(s or "").replace("\\", "\\\\").replace('"', '\\"')


def _gr_line_s(x1, y1, x2, y2, width=0.15):
    """板框线段：KiCad 9+ 用 (stroke ...) 包裹宽度"""
    return (
        "  (gr_line\n"
        f"    (start {_fmt(x1)} {_fmt(y1)})\n"
        f"    (end {_fmt(x2)} {_fmt(y2)})\n"
        "    (stroke\n"
        f"      (width {_fmt(width)})\n"
        "      (type default)\n"
        "    )\n"
        '    (layer "Edge.Cuts")\n'
        f'    (uuid "{_u()}")\n'
        "  )\n"
    )


def _footprint_s(c, fp, x, y):
    """元件封装实例：uuid 放在 layer 之后、at 之前，property 内也带 uuid"""
    ref = _esc(c["ref"])
    value = _esc(c.get("value", ""))
    return (
        f'  (footprint "{_esc(fp)}"\n'
        '    (layer "F.Cu")\n'
        f'    (uuid "{_u()}")\n'
        f'    (at {_fmt(x)} {_fmt(y)})\n'
        f'    (property "Reference" "{ref}"\n'
        "      (at 0 -2.54 0)\n"
        '      (layer "F.SilkS")\n'
        f'      (uuid "{_u()}")\n'
        "      (effects (font (size 1 1) (thickness 0.15)))\n"
        "    )\n"
        f'    (property "Value" "{value}"\n'
        "      (at 0 2.54 0)\n"
        '      (layer "F.Fab")\n'
        f'      (uuid "{_u()}")\n'
        "      (effects (font (size 1 1) (thickness 0.15)))\n"
        "    )\n"
        "  )\n"
    )


def build_pcb(design, board_w=80.0, board_h=60.0):
    comps = design.get("components", [])

    # 元件按网格摆放（每行 5 个，15mm 间距）
    rows, row = [], []
    for c in comps:
        row.append(c)
        if len(row) >= 5:
            rows.append(row)
            row = []
    if row:
        rows.append(row)

    footprints = ""
    y = 40.0
    for r in rows:
        x = 15.0
        for c in r:
            fp = c.get("footprint", "") or "Resistor_SMD:R_0805_2012Metric"
            if ":" not in fp:
                fp = "Package_DIP:DIP-8_W7.62mm"
            footprints += _footprint_s(c, fp, x, y)
            x += 15.0
        y += 15.0

    board_w = max(float(board_w), 60.0)
    board_h = max(float(board_h), 40.0 + (len(rows) - 1) * 15.0 if rows else 40.0)
    pts = [(0.0, 0.0), (board_w, 0.0), (board_w, board_h), (0.0, board_h), (0.0, 0.0)]
    edges = "".join(_gr_line_s(*pts[i], *pts[i + 1]) for i in range(len(pts) - 1))

    # 网络声明：net 0 保留为空网络，其余按 design.nets 顺序编号
    nets = ['  (net 0 "")\n']
    for i, net in enumerate(design.get("nets", []), start=1):
        nets.append(f'  (net {i} "{_esc(net.get("name", ""))}")\n')

    layers = "\n".join("    " + line for line in _LAYERS)
    title = _esc(design.get("title", "EDA Agent"))
    paper = _esc(design.get("paper", "A4") or "A4")

    pcb = (
        "(kicad_pcb\n"
        f"  (version {PCB_VERSION})\n"
        '  (generator "pcbnew")\n'
        f'  (generator_version "{GENERATOR_VERSION}")\n'
        "  (general\n"
        "    (thickness 1.6)\n"
        "    (legacy_teardrops no)\n"
        "  )\n"
        f'  (paper "{paper}")\n'
        "  (title_block\n"
        f'    (title "{title}")\n'
        "  )\n"
        "  (layers\n"
        f"{layers}\n"
        "  )\n"
        "  (setup\n"
        "    (pad_to_mask_clearance 0)\n"
        "    (allow_soldermask_bridges_in_footprints no)\n"
        "    (tenting front back)\n"
        "  )\n"
        f"{''.join(nets)}"
        f"{edges}"
        f"{footprints}"
        ")\n"
    )
    return pcb
