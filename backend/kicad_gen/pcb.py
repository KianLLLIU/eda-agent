# -*- coding: utf-8 -*-
"""
JSON 电路描述 → KiCad PCB (.kicad_pcb)

v2.0.5 起 PCB 是**真正可用的板子**，不再是「板框 + 文字」的空壳：

  * 封装从本机 KiCad 官方库（``share/kicad/footprints/*.pretty``）读取真实
    ``.kicad_mod`` 内联进板子，带焊盘、丝印、courtyard、3D 模型；库里找不到时
    按管脚数合成一个规整封装，保证任何机器都能出图。
  * 焊盘按设计网表挂 ``(net N "NAME")``，KiCad 里能看到飞线（连通关系）。
  * 排版用封装 courtyard 的真实尺寸做行式排布：同一模块挨在一起，行间留足
    间隙，板宽超限自动折行，绝不重叠。
  * 板框按内容自适应（内容 + 边距，并留出安装孔区域），四角倒圆角，板上
    居中摆放；大板自动加 4 个 M3 安装孔。

格式要点（KiCad 9/10，已用 10.0.7 的 kicad-cli 实测）：
  * 顶层**不能有** ``(uuid ...)``，uuid 只在元素内部；
  * 层编号用新版（0 F.Cu / 2 B.Cu / 25 Edge.Cuts ...）；
  * 图形用 ``(stroke (width ...) (type ...))``。
"""

from __future__ import annotations

import copy
import math
import uuid

from . import footprints as fplib

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

_PAPERS = {"A5": (210.0, 148.0), "A4": (297.0, 210.0), "A3": (420.0, 297.0), "A2": (594.0, 420.0)}

# 排版参数（mm）
_MAX_ROW_W = 96.0      # 单行最大宽度
_FP_GAP = 3.0          # 同排封装 courtyard 间距
_ROW_GAP = 4.0         # 行间距
_GROUP_GAP = 7.0       # 模块间距
_MARGIN = 4.0          # 无安装孔时的板边距
_HOLE_MARGIN = 9.5     # 有安装孔时，内容离板边的最小距离
_HOLE_INSET = 4.6      # 安装孔中心离板边
_MOUNT_FP = "MountingHole:MountingHole_3.2mm_M3"


def _u():
    return str(uuid.uuid4())


def _fmt(v):
    if isinstance(v, (int, float)):
        if abs(v - round(v)) < 1e-9:
            return str(int(round(v)))
        return f"{v:.3f}".rstrip("0").rstrip(".")
    return str(v)


def _esc(s):
    return str(s or "").replace("\\", "\\\\").replace('"', '\\"')


def _snap(v, grid=0.635):
    return round(v / grid) * grid


# ------------------------------------------------------------------ 板框 / 图形

def _gr_line(x1, y1, x2, y2, width=0.15, layer="Edge.Cuts"):
    return [
        fplib.Atom("gr_line"),
        [fplib.Atom("start"), fplib.Atom(_fmt(x1)), fplib.Atom(_fmt(y1))],
        [fplib.Atom("end"), fplib.Atom(_fmt(x2)), fplib.Atom(_fmt(y2))],
        [fplib.Atom("stroke"), [fplib.Atom("width"), fplib.Atom(_fmt(width))],
         [fplib.Atom("type"), fplib.Atom("default")]],
        [fplib.Atom("layer"), fplib.Str(layer)],
        [fplib.Atom("uuid"), fplib.Str(_u())],
    ]


def _gr_arc(cx, cy, r, a0, a1, width=0.15, layer="Edge.Cuts"):
    """按 start / mid / end 三点定义圆弧（KiCad 9+ 写法）"""
    def pt(deg):
        rad = math.radians(deg)
        return cx + r * math.cos(rad), cy + r * math.sin(rad)

    sx, sy = pt(a0)
    mx, my = pt((a0 + a1) / 2.0)
    ex, ey = pt(a1)
    return [
        fplib.Atom("gr_arc"),
        [fplib.Atom("start"), fplib.Atom(_fmt(sx)), fplib.Atom(_fmt(sy))],
        [fplib.Atom("mid"), fplib.Atom(_fmt(mx)), fplib.Atom(_fmt(my))],
        [fplib.Atom("end"), fplib.Atom(_fmt(ex)), fplib.Atom(_fmt(ey))],
        [fplib.Atom("stroke"), [fplib.Atom("width"), fplib.Atom(_fmt(width))],
         [fplib.Atom("type"), fplib.Atom("default")]],
        [fplib.Atom("layer"), fplib.Str(layer)],
        [fplib.Atom("uuid"), fplib.Str(_u())],
    ]


def _gr_text(text, x, y, size=1.0, layer="F.SilkS", justify=None):
    effects = [[fplib.Atom("font"),
                [fplib.Atom("size"), fplib.Atom(_fmt(size)), fplib.Atom(_fmt(size))],
                [fplib.Atom("thickness"), fplib.Atom("0.15")]]]
    # 水平居中 + 垂直居中都是 KiCad 默认值，不要显式写 center（不是合法 token）
    if justify in ("left", "right", "mirror"):
        effects.append([fplib.Atom("justify"), fplib.Atom(justify)])
    return [
        fplib.Atom("gr_text"), fplib.Str(text),
        [fplib.Atom("at"), fplib.Atom(_fmt(x)), fplib.Atom(_fmt(y)), fplib.Atom("0")],
        [fplib.Atom("layer"), fplib.Str(layer)],
        [fplib.Atom("uuid"), fplib.Str(_u())],
        [fplib.Atom("effects"), *effects],
    ]


def _board_outline(x0, y0, x1, y1, radius=2.0):
    """圆角矩形板框（Edge.Cuts）。半径过小时退化为直角。"""
    r = min(radius, (x1 - x0) / 4.0, (y1 - y0) / 4.0)
    if r < 0.5:
        return [
            _gr_line(x0, y0, x1, y0), _gr_line(x1, y0, x1, y1),
            _gr_line(x1, y1, x0, y1), _gr_line(x0, y1, x0, y0),
        ]
    return [
        _gr_line(x0 + r, y0, x1 - r, y0),
        _gr_arc(x1 - r, y0 + r, r, 270, 360),
        _gr_line(x1, y0 + r, x1, y1 - r),
        _gr_arc(x1 - r, y1 - r, r, 0, 90),
        _gr_line(x1 - r, y1, x0 + r, y1),
        _gr_arc(x0 + r, y1 - r, r, 90, 180),
        _gr_line(x0, y1 - r, x0, y0 + r),
        _gr_arc(x0 + r, y0 + r, r, 180, 270),
    ]


# ------------------------------------------------------------------ 封装实例

def _instance(fp, lib_id, ref, value, x, y, rot, netmap):
    """把库里的封装转成板内实例：改名字、加 uuid/at、填 ref/value、焊盘挂网络

    必须 deepcopy：封装节点来自 fplib 的缓存，多个实例共用同一份对象时，
    后写入的 Reference / net 会覆盖前面的（表现为所有电容都叫 C4）。
    """
    fp = copy.deepcopy(fp)
    body = []
    for idx, ch in enumerate(fp[1:]):
        if idx == 0 and not isinstance(ch, list):
            continue  # 库里封装自带的 "名字" 字符串，已由 lib_id 取代
        if isinstance(ch, list) and ch and ch[0] in (
                "version", "generator", "generator_version", "embedded_fonts"):
            continue
        body.append(ch)

    out = [fplib.Atom("footprint"), fplib.Str(lib_id)]
    layer = next((c for c in body if isinstance(c, list) and c and c[0] == "layer"), None)
    out.append(layer or [fplib.Atom("layer"), fplib.Str("F.Cu")])
    out.append([fplib.Atom("uuid"), fplib.Str(_u())])
    at = [fplib.Atom("at"), fplib.Atom(_fmt(x)), fplib.Atom(_fmt(y))]
    if rot:
        at.append(fplib.Atom(_fmt(rot)))
    out.append(at)

    for ch in body:
        if ch is layer:
            continue
        if isinstance(ch, list) and ch and ch[0] == "property":
            name = str(ch[1]) if len(ch) > 1 else ""
            if name == "Reference":
                ch[2] = fplib.Str(ref)
            elif name == "Value":
                ch[2] = fplib.Str(value or lib_id.split(":")[-1])
        elif isinstance(ch, list) and ch and ch[0] == "pad":
            pin = str(ch[1]) if len(ch) > 1 else ""
            ch[:] = [n for n in ch if not (isinstance(n, list) and n and n[0] in ("net", "uuid"))]
            net = netmap.get((ref, pin))
            ch.append([fplib.Atom("uuid"), fplib.Str(_u())])
            if net:
                ch.insert(len(ch) - 1, [fplib.Atom("net"),
                                        fplib.Atom(str(net[0])), fplib.Str(net[1])])
        out.append(ch)
    return out


def _hide_property(node, name):
    """把某个 property（如安装孔的 Reference）设为隐藏，避免丝印压板边"""
    for ch in node:
        if (isinstance(ch, list) and ch and ch[0] == "property"
                and len(ch) > 1 and str(ch[1]) == name):
            if any(isinstance(x, list) and x and x[0] == "hide" for x in ch):
                return
            idx = next((i for i, x in enumerate(ch)
                        if isinstance(x, list) and x and x[0] == "layer"), len(ch) - 1)
            ch.insert(idx + 1, [fplib.Atom("hide"), fplib.Atom("yes")])
            return


# ------------------------------------------------------------------ 排版

def _measure(design):
    """为每个元件准备封装、尺寸与旋转，返回 [(ref, comp, fp, lib_id, w, h, rot)]"""
    try:
        from .symbols import get_symbol
    except Exception:  # noqa: BLE001
        get_symbol = None

    items = []
    for c in design.get("components", []):
        ref = c.get("ref", "?")
        rp = c.get("footprint") or ""
        net_pins = {str(x.get("pin")) for n in design.get("nets", [])
                    for x in n.get("connections", []) if x.get("ref") == ref}
        npins = len(net_pins)
        lib_id = fplib.resolve(rp, npins)
        fp = fplib.load_footprint(lib_id) if lib_id else None
        if fp is None:
            # 库里没有：按符号管脚数合成封装（保证没装 KiCad 的机器也能出图）
            nsym = 0
            if get_symbol:
                try:
                    sym = get_symbol("%s:%s" % (c.get("lib") or "Device", c.get("symbol") or ""))
                    nsym = len((sym or {}).get("pins") or [])
                except Exception:  # noqa: BLE001
                    nsym = 0
            npins = max(npins, nsym, 2)
            lib_id = rp if (rp and ":" in rp) else "Synthetic:" + (c.get("symbol") or "Part")
            smd = ("SMD" in rp.upper()) or ("DIP" not in rp.upper())
            fp = fplib.synthetic_footprint(lib_id, npins, smd=smd)
        minx, miny, maxx, maxy = fplib.footprint_extent(fp)
        w, h = maxx - minx, maxy - miny
        # 细高的封装（排针等）转 90° 更省板面
        rot = 90 if (h > 2.0 * w and h >= 12.0) else 0
        if rot:
            w, h = h, w
        items.append({"ref": ref, "comp": c, "fp": fp, "lib": lib_id,
                      "w": w, "h": h, "rot": rot, "off": (minx, miny, maxx, maxy)})
    return items


def _grouped(design, items):
    by_ref = {it["ref"]: it for it in items}
    groups, seen = [], set()
    for g in design.get("groups") or []:
        refs = [r for r in (g.get("refs") or []) if r in by_ref]
        if refs:
            groups.append((g.get("name") or "模块", refs))
            seen.update(refs)
    rest = [it["ref"] for it in items if it["ref"] not in seen]
    if rest:
        groups.append(("其他", rest))
    return groups


def _place(design, items, inset):
    """两段式排版：先把每个模块内部排成行（得到「块」），再把块流式换行铺开。

    返回 (positions, content_w, content_h)，坐标为板内绝对坐标。
    模块内部的元件紧挨在一起，模块之间留更大的间距，视觉上自然成组，
    空板面积也更小。
    """
    by_ref = {it["ref"]: it for it in items}
    groups = _grouped(design, items)

    # ---- 1) 模块内部排版，得到块（局部坐标）
    blocks = []
    for _, refs in groups:
        rows, cur, cur_w = [], [], 0.0
        for ref in refs:
            it = by_ref[ref]
            add = it["w"] if not cur else _FP_GAP + it["w"]
            if cur and cur_w + add > _MAX_ROW_W:
                rows.append(cur)
                cur, cur_w = [(ref, it["w"], it["h"])], it["w"]
            else:
                cur.append((ref, it["w"], it["h"]))
                cur_w += add
        if cur:
            rows.append(cur)

        laid, y, bw = [], 0.0, 0.0
        for ri, row in enumerate(rows):
            row_w = sum(w for _, w, _ in row) + _FP_GAP * (len(row) - 1)
            row_h = max(h for _, _, h in row)
            x, prev_w = 0.0, 0.0
            for i, (ref, w, h) in enumerate(row):
                # 中心距 = 前一个半宽 + 间距 + 当前半宽（第一颗只加自身半宽）
                x = w / 2.0 if i == 0 else (x + prev_w / 2.0 + _FP_GAP + w / 2.0)
                prev_w = w
                laid.append((ref, x, y + row_h / 2.0))
            bw = max(bw, row_w)
            y += row_h + (_ROW_GAP if ri != len(rows) - 1 else 0.0)
        blocks.append({"w": bw, "h": y, "laid": laid})

    # ---- 2) 块按行铺开，超出宽度就换行
    rows_of_blocks, cur, cur_w = [], [], 0.0
    for b in blocks:
        add = b["w"] if not cur else _GROUP_GAP + b["w"]
        if cur and cur_w + add > _MAX_ROW_W:
            rows_of_blocks.append(cur)
            cur, cur_w = [b], b["w"]
        else:
            cur.append(b)
            cur_w += add
    if cur:
        rows_of_blocks.append(cur)

    content_w = 0.0
    for r in rows_of_blocks:
        content_w = max(content_w, sum(b["w"] for b in r) + _GROUP_GAP * (len(r) - 1))

    positions, y0, content_h = {}, 0.0, 0.0
    for r in rows_of_blocks:
        row_h = max(b["h"] for b in r)
        x = 0.0
        for bi, b in enumerate(r):
            if bi:
                x += _GROUP_GAP
            dy = (row_h - b["h"]) / 2.0
            for ref, bx, by in b["laid"]:
                positions[ref] = (_snap(inset + x + bx, 0.05),
                                  _snap(inset + y0 + dy + by, 0.05))
            x += b["w"]
        y0 += row_h + _GROUP_GAP
        content_h = y0 - _GROUP_GAP
    return positions, content_w, content_h


# ------------------------------------------------------------------ 主函数

def build_pcb(design, board_w=None, board_h=None):
    items = _measure(design)
    nets = design.get("nets", [])

    netmap = {}
    for i, net in enumerate(nets, start=1):
        name = net.get("name", "") or f"N{i}"
        for conn in net.get("connections", []):
            netmap[(conn.get("ref"), str(conn.get("pin")))] = (i, name)
    net_nodes = [[fplib.Atom("net"), fplib.Atom("0"), fplib.Str("")]]
    for i, net in enumerate(nets, start=1):
        net_nodes.append([fplib.Atom("net"), fplib.Atom(str(i)),
                          fplib.Str(net.get("name", "") or f"N{i}")])

    # 先用无安装孔的边距量一遍内容，决定板子大小是否需要安装孔
    probe_pos, probe_w, probe_h = _place(design, items, _MARGIN)
    need_holes = (probe_w + 2 * _HOLE_MARGIN) >= 70.0 and (probe_h + 2 * _HOLE_MARGIN) >= 45.0
    inset = _HOLE_MARGIN if need_holes else _MARGIN

    positions, content_w, content_h = _place(design, items, inset)
    bw = _snap(content_w + 2 * inset, 0.5)
    bh = _snap(content_h + 2 * inset, 0.5)
    bw = max(bw, 38.0)
    bh = max(bh, 20.0)
    if board_w:
        bw = max(float(board_w), bw)
    if board_h:
        bh = max(float(board_h), bh)

    page = _PAPERS.get(str(design.get("paper") or "A4").upper(), _PAPERS["A4"])
    off_x = _snap((page[0] - bw) / 2.0, 0.5)
    off_y = _snap((page[1] - bh) / 2.0, 0.5)
    if off_x < 5 or off_y < 5:
        off_x, off_y = 10.0, 10.0

    # 板子被最小尺寸/指定尺寸撑大时，把内容在板内居中，避免挤在一侧
    extra_x = max(0.0, (bw - (content_w + 2 * inset)) / 2.0)
    extra_y = max(0.0, (bh - (content_h + 2 * inset)) / 2.0)

    # ---- 封装实例
    fp_nodes = []
    for it in items:
        x, y = positions[it["ref"]]
        x += extra_x
        y += extra_y
        minx, miny, maxx, maxy = it["off"]
        cx, cy = (minx + maxx) / 2.0, (miny + maxy) / 2.0
        if it["rot"] == 90:
            # KiCad 的 90° 把封装局部点 (px,py) 映射到 (py, -px)，
            # 所以要让 courtyard 中心落在 (x,y)，原点必须是 (x-cy, y+cx)
            x, y = x - cy, y + cx
        else:
            x, y = x - cx, y - cy
        fp_nodes.append(_instance(it["fp"], it["lib"], it["ref"],
                                  it.get("comp", {}).get("value", ""),
                                  off_x + x, off_y + y, it["rot"], netmap))

    # ---- 安装孔
    if need_holes:
        mh = fplib.load_footprint(_MOUNT_FP)
        if mh is not None:
            hx0, hy0 = off_x + _HOLE_INSET, off_y + _HOLE_INSET
            hx1, hy1 = off_x + bw - _HOLE_INSET, off_y + bh - _HOLE_INSET
            for i, (hx, hy) in enumerate(((hx0, hy0), (hx1, hy0), (hx0, hy1), (hx1, hy1)), start=1):
                node = _instance(mh, _MOUNT_FP, f"H{i}", "MountingHole", hx, hy, 0, {})
                _hide_property(node, "Reference")
                _hide_property(node, "Value")
                node.append([fplib.Atom("attr"), fplib.Atom("exclude_from_pos_files"),
                             fplib.Atom("exclude_from_bom")])
                fp_nodes.append(node)

    title = _esc(design.get("title") or "EDA Agent")
    edges = _board_outline(off_x, off_y, off_x + bw, off_y + bh,
                           radius=2.0 if min(bw, bh) > 30 else 0.0)

    # 丝印只在板内留一行标题（放在下边距里，和元件 courtyard 不冲突）
    texts = []
    if bh >= 16:
        texts.append(_gr_text(_esc(design.get("title") or "EDA Agent")[:44],
                              off_x + bw / 2.0, off_y + bh - 2.2, size=0.9))

    layers = "\n".join("    " + line for line in _LAYERS)
    setup = "\n".join([
        "  (setup",
        "    (pad_to_mask_clearance 0)",
        "    (allow_soldermask_bridges_in_footprints no)",
        "    (tenting front back)",
        "  )",
    ])

    parts = [
        "(kicad_pcb",
        f"  (version {PCB_VERSION})",
        '  (generator "pcbnew")',
        f'  (generator_version "{GENERATOR_VERSION}")',
        "  (general",
        "    (thickness 1.6)",
        "    (legacy_teardrops no)",
        "  )",
        f'  (paper "{_esc(design.get("paper") or "A4")}")',
        "  (title_block",
        f'    (title "{title}")',
        f'    (comment 1 "Generated by EDA Agent")',
        "  )",
        "  (layers",
        layers,
        "  )",
        setup,
    ]
    for n in net_nodes:
        parts.append("  " + fplib.dump(n, 1).replace("\n  ", "\n    "))
    for n in edges + texts + fp_nodes:
        parts.append(fplib.dump(n, 1))
    parts.append(")")
    return "\n".join(parts) + "\n"
