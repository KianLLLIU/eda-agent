# -*- coding: utf-8 -*-
"""
统一电路布局引擎（SVG 实时构图 + KiCad 原理图共用）

v2.0.3 之前，SVG 直接复用 schematic.py 的简易布局，一行硬塞 5 个元件、
模块框只按符号包围盒外扩 3mm，label 和相邻行经常压在一起；连线又是斜线串联，
视觉上既挤又像断线。这里改为「规整网格 + 独立布线通道」：

  · 每个模块单独成块，块内元件放进等宽 slot 网格（每行最多 4 个）
  · slot 尺寸包含元件图形 + ref/value 标签空间，模块框留出标题与内边距
  · 每条网络分配一条独立水平 lane（放在所有元件下方），
    引脚先向外引 stub 再垂直下到 lane，主干水平连通 —— 正交、不穿元件、不缺线
  · 单引脚网络同样有 stub + 端点 + 标签，不再被跳过
  · 返回完整 bounds，画布不会裁掉标题、模块名或连线
"""

from __future__ import annotations

import math

from .symbols import get_symbol

GRID = 1.27

# ---- 布局常量（单位 mm，与 KiCad 原理图同一坐标系）----
MAX_COLS = 4            # 每行最多几个元件，避免一行拉太长
CELL_PAD_X = 5.0        # 元件卡片左右内边距
CELL_PAD_Y = 4.0        # 元件卡片上下内边距
LABEL_SPACE = 7.0       # ref / value 文字预留高度
SLOT_GAP_X = 10.0       # 相邻 slot 之间的空隙（也是走线避让区）
ROW_GAP = 5.0           # 同一模块内行间距
GROUP_PAD_X = 7.0
GROUP_PAD_TOP = 11.0    # 模块标题空间
GROUP_PAD_BOTTOM = 7.0
GROUP_GAP_Y = 22.0      # 模块之间（必须大于上下 padding 之和，否则模块框会重叠）
X_ORIGIN = 22.0
TITLE_H = 34.0          # 顶部标题栏
PAGE_PAD = 14.0
LANE_GAP = 4.6          # 每条网络通道的间距
LANE_TOP_GAP = 7.0      # 元件区与第一条 lane 的距离
FOOTER_H = 16.0         # 底部图例 / 署名高度
STUB = 3.4              # 引脚向外引出的短水平段


def snap(v):
    """对齐到 1.27mm 网格"""
    return round(round(v / GRID) * GRID, 3)


def _fmt(v):
    if isinstance(v, (int, float)):
        if abs(v - round(v)) < 1e-9:
            return str(int(round(v)))
        return f"{v:.2f}".rstrip("0").rstrip(".")
    return str(v)


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


def pin_world(comp_x, comp_y, rot, px, py):
    """符号局部坐标 → 画布世界坐标（局部 y 向上、画布 y 向下）"""
    rad = math.radians(rot)
    cos, sin = math.cos(rad), math.sin(rad)
    dy = -py
    wx = px * cos + dy * sin
    wy = -px * sin + dy * cos
    return snap(comp_x + wx), snap(comp_y + wy)


def _groups_of(design):
    comps = design.get("components", [])
    comp_by_ref = {c["ref"]: c for c in comps}
    group_order, ref_to_group, members = [], {}, {}

    for g in design.get("groups", []) or []:
        name = g.get("name") or "模块"
        refs = [r for r in g.get("refs", []) if r in comp_by_ref]
        if not refs:
            continue
        if name in members:            # 重名分组加后缀，避免相互覆盖
            name = "%s %d" % (name, group_order.count(name) + 1)
        group_order.append(name)
        members[name] = refs
        for r in refs:
            ref_to_group[r] = name

    ungrouped = [c["ref"] for c in comps if c["ref"] not in ref_to_group]
    if ungrouped:
        group_order.append("其他")
        members["其他"] = ungrouped
        for r in ungrouped:
            ref_to_group[r] = "其他"

    if not group_order and comps:
        group_order = ["电路"]
        members["电路"] = [c["ref"] for c in comps]
        for r in members["电路"]:
            ref_to_group[r] = "电路"
    return comp_by_ref, group_order, ref_to_group, members


def _cell_sizes(comps):
    cells = {}
    for c in comps:
        sym = get_symbol(f'{c["lib"]}:{c["symbol"]}')
        w, h = symbol_bbox(sym) if sym else (10.0, 10.0)
        cells[c["ref"]] = (w + 2 * CELL_PAD_X, h + 2 * CELL_PAD_Y + LABEL_SPACE)
    return cells


def compute_layout(design, max_cols=MAX_COLS, title_h=TITLE_H,
                   group_gap=GROUP_GAP_Y, lane_gap=LANE_GAP, x_origin=X_ORIGIN):
    """计算完整布局，返回给 SVG / 原理图共用的结构化结果。

    SVG 用默认参数（含标题栏、较宽的模块间距、独立网络通道）；
    KiCad 原理图传 title_h=8 / group_gap=10 / max_cols=5，让内容落在 A4 页面内。
    """
    comps = design.get("components", [])
    comp_by_ref, group_order, ref_to_group, members = _groups_of(design)
    cells = _cell_sizes(comps)

    # 模块框 = 本模块底部 padding + 下一模块顶部 padding，
    # 间距必须大于两者之和，否则相邻虚线框在视觉上会叠在一起。
    group_gap = max(float(group_gap), GROUP_PAD_BOTTOM + GROUP_PAD_TOP + 2.0)

    positions = {}
    group_boxes = {}
    y_cursor = title_h + group_gap
    max_right = x_origin

    # 所有模块共用同一个 slot 宽度：列网格全局对齐，
    # 这样列间空隙在每一行都是同一条竖直通道，走线不会穿过任何元件卡片。
    all_cell_w = [cells[r][0] for refs in members.values() for r in refs]
    global_slot_w = (max(all_cell_w) + SLOT_GAP_X) if all_cell_w else 20.0
    slot_half = (global_slot_w - SLOT_GAP_X) / 2.0   # 卡片半宽（按最宽元件）

    for gname in group_order:
        refs = members.get(gname, [])
        if not refs:
            continue
        cols = min(len(refs), max(max_cols, 1))
        rows = math.ceil(len(refs) / cols)
        slot_w = global_slot_w

        row_heights = []
        for i in range(rows):
            chunk = refs[i * cols:(i + 1) * cols]
            row_heights.append(max(cells[r][1] for r in chunk) if chunk else 0.0)

        gy0 = y_cursor
        cy_cursor = y_cursor
        for i in range(rows):
            chunk = refs[i * cols:(i + 1) * cols]
            for j, r in enumerate(chunk):
                cx = x_origin + j * slot_w + slot_w / 2
                cy = cy_cursor + row_heights[i] / 2
                positions[r] = (snap(cx), snap(cy))
            cy_cursor += row_heights[i] + ROW_GAP

        total_h = cy_cursor - ROW_GAP - gy0
        box_w = cols * slot_w - SLOT_GAP_X
        group_boxes[gname] = (
            x_origin - GROUP_PAD_X,
            gy0 - GROUP_PAD_TOP,
            x_origin + box_w + GROUP_PAD_X,
            gy0 + total_h + GROUP_PAD_BOTTOM,
        )
        max_right = max(max_right, x_origin + box_w + GROUP_PAD_X)
        y_cursor = gy0 + total_h + group_gap

    content_bottom = max([b[3] for b in group_boxes.values()], default=y_cursor)

    # ---- 网络：收集每个连接的引脚世界坐标与出线方向 ----
    net_points = {}
    for net in design.get("nets", []) or []:
        name = net.get("name") or "NET"
        pts = []
        for conn in net.get("connections", []) or []:
            ref = conn.get("ref")
            pin_no = str(conn.get("pin", ""))
            comp = comp_by_ref.get(ref)
            if comp is None or ref not in positions:
                continue
            sym = get_symbol(f'{comp["lib"]}:{comp["symbol"]}')
            if sym is None:
                continue
            pin = next((p for p in sym["pins"] if p[0] == pin_no), None)
            if pin is None:
                continue
            cx, cy = positions[ref]
            wx, wy = pin_world(cx, cy, 0, pin[3], pin[4])
            # 引脚在元件左侧还是右侧，决定 stub 往哪边引。
            # stub 终点固定在「卡片外沿 + 2mm」的列间空隙：同一列所有元件共用
            # 该竖直通道，导线不会穿过自己或下方元件的图形。
            side = 1 if wx >= cx else -1
            stub = max(slot_half + 2.0 - abs(wx - cx), STUB)
            pts.append({
                "x": wx, "y": wy, "ref": ref, "pin": pin_no,
                "side": side, "stub_x": snap(wx + side * stub),
            })
        net_points[name] = pts

    # 不同网络的垂直支线绝不能共用同一个 x：两条竖线重合会把不同网络短接，
    # KiCad ERC 会报 multiple_net_names。这里做全局唯一化（同网络内允许相同）。
    used_stub_x = []          # [(x, net_name)]
    for name, pts in net_points.items():
        for p in pts:
            x = p["stub_x"]
            for _ in range(48):
                if not any(abs(x - ux) < 0.01 and owner != name
                           for ux, owner in used_stub_x):
                    break
                x = snap(x + p["side"] * GRID)
            p["stub_x"] = x
            used_stub_x.append((x, name))

    # ---- 水平通道分配 ----
    # 旧方案把所有通道排在图的最下方，元件区靠上的网络就要拉一条贯穿全图的
    # 竖线，几十个元件时整张图像「一片栅栏」。现在改成两级通道：
    #   ① 每个模块框下方的空隙里放 1~3 条通道（就近布线，竖线只走一格）；
    #   ② 所有模块都放不下的网络才落到图底部的通栏区。
    # 同一 y 上的通道仍按 x 区间着色，不会互相压线；不同 y 之间互不影响。
    lanes = {}
    band_spans = {}              # y -> [(left, right)]

    def _center_x(item):
        name, pts = item
        return (sum(p["stub_x"] for p in pts) / len(pts)) if pts else x_origin

    cand_ys = []
    for gname in group_order:
        box = group_boxes.get(gname)
        if not box:
            continue
        # 框下方可用空间 = group_gap - (上 padding + 下 padding)，通道居中摆放，
        # 避免压在模块虚线框上
        room = group_gap - GROUP_PAD_BOTTOM - GROUP_PAD_TOP
        n_fit = max(1, int((room - 2.0) // lane_gap))
        first = box[3] + max(2.0, (room - (n_fit - 1) * lane_gap) / 2.0)
        for k in range(n_fit):
            cand_ys.append(snap(first + k * lane_gap))
    lane_base = content_bottom + LANE_TOP_GAP
    for k in range(12):
        cand_ys.append(snap(lane_base + k * lane_gap))
    # 去重：不同来源算出的候选 y 可能只差一两毫米，太近会让相邻两条通道的
    # 网络名叠在一起
    cand_ys = sorted(set(cand_ys))
    spaced = []
    for y in cand_ys:
        if not spaced or y - spaced[-1] >= lane_gap * 0.9:
            spaced.append(y)
    cand_ys = spaced

    # 从右往左分配：右侧网络走靠下的通道，竖线扇形散开不打架
    for name, pts in sorted(net_points.items(), key=_center_x, reverse=True):
        xs = [p["stub_x"] for p in pts]
        left = (min(xs) - 2.6) if xs else x_origin
        right = (max(xs) + 2.6) if xs else x_origin + 10
        need = (max(p["y"] for p in pts) if pts else content_bottom) + 2.0
        chosen = None
        for y in cand_ys:
            if y < need:
                continue
            spans = band_spans.setdefault(y, [])
            if all(left > r + 1.0 or right < l - 1.0 for (l, r) in spans):
                spans.append((left, right))
                chosen = y
                break
        if chosen is None:                       # 兜底：接在最后一条下面
            chosen = snap((max(lanes.values()) if lanes else lane_base) + lane_gap)
            band_spans.setdefault(chosen, []).append((left, right))
        lanes[name] = chosen

    lane_bottom = (max(lanes.values()) if lanes else lane_base)
    right_edge = max_right
    for pts in net_points.values():
        for p in pts:
            right_edge = max(right_edge, p["stub_x"] + 6)

    bounds = (0.0, 0.0,
              snap(right_edge + PAGE_PAD),
              snap(lane_bottom + FOOTER_H + PAGE_PAD))

    return {
        "positions": positions,
        "group_order": group_order,
        "ref_to_group": ref_to_group,
        "group_boxes": group_boxes,
        "cells": cells,
        "net_points": net_points,
        "lanes": lanes,
        "bounds": bounds,
        "content_bottom": content_bottom,
        "lane_bottom": lane_bottom,
        "title": design.get("title") or "未命名电路",
        "stats": {
            "components": len(comps),
            "nets": len(net_points),
            "groups": len(group_order),
            "connections": sum(len(v) for v in net_points.values()),
        },
    }
