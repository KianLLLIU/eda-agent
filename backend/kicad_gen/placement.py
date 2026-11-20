# -*- coding: utf-8 -*-
"""智能布局引擎（v2.2.0）

借鉴 KiCadRoutingTools（MIT）的「功能分组 + 模拟退火 + 线长代价」思路，
但完全自研、零第三方依赖，直接吃本项目的 design JSON。

解决 v2.1.0 的布局痛点：
  1. 原理图：列宽全局取最宽元件 → 窄元件被撑出巨缝。改为**变宽列**。
  2. 元件顺序照抄 JSON → 强连通元件隔很远。改为按**网表亲和度**排序。
  3. PCB：行式排版不考虑连线 → 飞线乱、交叉多。改为**模拟退火**优化
     HPWL（半周长线长）+ 重叠 + 组连续性 + 越界。

所有随机过程带 seed，同样输入必得同样布局（可复现、可回归）。
"""

from __future__ import annotations

import math
import random

GRID_SCHEMATIC = 1.27
GRID_PCB = 0.635


def _snap(v, grid):
    return round(round(v / grid) * grid, 4)


# ---------------------------------------------------------------- 网表亲和度

def affinity_graph(design):
    """构建元件亲和图：ref -> {other_ref: weight}。

    连接越多的两个元件权重越大；电源/地网络降权（否则所有元件都会被
    VCC 拉到一起）。返回值是无向图的邻接表。
    """
    aff = {}
    for c in design.get("components", []) or []:
        aff.setdefault(c.get("ref"), {})
    for net in design.get("nets", []) or []:
        name = (net.get("name") or "").upper()
        # 电源网络权重要低，否则干扰信号流的局部聚类
        w = 0.25 if any(k in name for k in ("VCC", "GND", "3V3", "5V", "+")) else 1.0
        pins = {c.get("ref") for c in net.get("connections", []) if c.get("ref") in aff}
        # 一个网络有 n 个引脚时产生 n*(n-1)/2 条边；大网络降权避免主导
        if len(pins) > 1:
            w = w * 2.0 / max(1, len(pins) - 1)
            for a in pins:
                for b in pins:
                    if a != b:
                        aff[a][b] = aff[a].get(b, 0.0) + w
    return aff


def order_refs(refs, aff):
    """按网表亲和度给元件排序：从连接最多的出发，每次挑与已排序列最相关的。"""
    remaining = list(refs)
    if not remaining:
        return []
    order = []
    # 起点：总亲和度最高
    cur = max(remaining, key=lambda r: (sum(aff.get(r, {}).values()), r))
    remaining.remove(cur)
    order.append(cur)
    while remaining:
        placed = set(order)
        nxt = max(
            remaining,
            key=lambda r: (sum(aff.get(r, {}).get(p, 0.0) for p in placed),
                           sum(aff.get(r, {}).values()), r),
        )
        remaining.remove(nxt)
        order.append(nxt)
    return order


def order_groups(group_order, members, aff):
    """按跨组连接强度重排模块：连得紧的模块排相邻。"""
    if len(group_order) <= 1:
        return list(group_order)
    remaining = list(group_order)
    strength = {}
    for i, a in enumerate(group_order):
        for b in group_order[i + 1:]:
            s = sum(aff.get(x, {}).get(y, 0.0)
                    for x in members.get(a, []) for y in members.get(b, []))
            strength[(a, b)] = strength[(b, a)] = s
    first = max(remaining,
                key=lambda g: (sum(strength.get((g, o), 0.0) for o in remaining if o != g), g))
    remaining.remove(first)
    result = [first]
    while remaining:
        nxt = max(remaining,
                  key=lambda g: (sum(strength.get((g, p), 0.0) for p in result), g))
        remaining.remove(nxt)
        result.append(nxt)
    return result


# ---------------------------------------------------------------- 原理图布局

def layout_schematic(design, cells, max_cols=4, x_origin=22.0, y_origin=40.0,
                     row_gap=5.0, group_pad_x=7.0, group_pad_top=11.0,
                     group_pad_bottom=7.0, group_gap=20.0, slot_gap=10.0):
    """变宽列 + 亲和度排序的原理图布局。

    返回 (positions, group_order, members, group_boxes, bounds)。
    cells: ref -> (cell_w, cell_h)。
    """
    aff = affinity_graph(design)
    comp_by_ref = {c["ref"]: c for c in design.get("components", []) or []}

    # 分组（兼容旧结构 + 重名处理）
    members, ref_to_group, group_order = {}, {}, []
    for g in design.get("groups", []) or []:
        name = g.get("name") or "模块"
        refs = [r for r in (g.get("refs") or []) if r in comp_by_ref]
        if not refs:
            continue
        if name in members:
            name = "%s %d" % (name, group_order.count(name) + 1)
        group_order.append(name)
        members[name] = refs
        for r in refs:
            ref_to_group[r] = name
    rest = [r for r in comp_by_ref if r not in ref_to_group]
    if rest:
        group_order.append("其他")
        members["其他"] = rest
    if not group_order and comp_by_ref:
        group_order, members = ["电路"], {"电路": list(comp_by_ref)}
    group_order = order_groups(group_order, members, aff)

    # 每组内按亲和度排序 → 切成变宽列网格
    positions, group_boxes = {}, {}
    y_cursor = y_origin
    max_right = x_origin

    for gname in group_order:
        refs = order_refs(members[gname], aff)
        cols = min(len(refs), max(1, max_cols))
        rows = math.ceil(len(refs) / cols)
        matrix = [refs[i * cols:(i + 1) * cols] for i in range(rows)]

        # 每列宽度 = 该列最宽元件 + 间隙（关键改进：不再全局统一）
        col_w = []
        for j in range(cols):
            widths = [cells[r][0] for row in matrix if j < len(row) for r in [row[j]]]
            col_w.append((max(widths) if widths else 12.0) + slot_gap)
        x_offsets = [x_origin]
        for w in col_w[:-1]:
            x_offsets.append(x_offsets[-1] + w)

        cy = y_cursor
        for i, row in enumerate(matrix):
            row_h = max(cells[r][1] for r in row)
            for j, r in enumerate(row):
                # 元件在自己的变宽列里居中
                cx = x_offsets[j] + (col_w[j] - slot_gap) / 2.0
                positions[r] = (_snap(cx, GRID_SCHEMATIC),
                                _snap(cy + row_h / 2.0, GRID_SCHEMATIC))
            cy += row_h + row_gap
        total_h = cy - row_gap - y_cursor
        box_w = sum(col_w) - slot_gap
        group_boxes[gname] = (
            _snap(x_origin - group_pad_x, GRID_SCHEMATIC),
            _snap(y_cursor - group_pad_top, GRID_SCHEMATIC),
            _snap(x_origin + box_w + group_pad_x, GRID_SCHEMATIC),
            _snap(y_cursor + total_h + group_pad_bottom, GRID_SCHEMATIC),
        )
        max_right = max(max_right, x_origin + box_w + group_pad_x)
        y_cursor = y_cursor + total_h + group_gap

    bounds = (0.0, 0.0, _snap(max_right + 14.0, GRID_SCHEMATIC),
              _snap(y_cursor + 16.0, GRID_SCHEMATIC))
    return positions, group_order, members, group_boxes, bounds


# ---------------------------------------------------------------- PCB 布局

def _hpwl(nets, centers):
    """半周长线长（Half-Perimeter Wire Length），布线布局的标准代价。"""
    total = 0.0
    for net in nets:
        pts = [centers[c["ref"]] for c in net.get("connections", [])
               if c.get("ref") in centers]
        if len(pts) < 2:
            continue
        total += (max(p[0] for p in pts) - min(p[0] for p in pts)
                  + max(p[1] for p in pts) - min(p[1] for p in pts))
    return total


def _overlap_area(a, b):
    ox = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    oy = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    return ox * oy


def layout_pcb(design, items, seed=42, iterations=2200, target_w=None, target_h=None):
    """模拟退火 PCB 布局。

    items: [{ref, w, h, rot, ...}]（w/h 已是旋转后的 courtyard 尺寸）
    返回 (positions, metrics)。positions: ref -> (x, y)。
    """
    rng = random.Random(seed)
    refs = [it["ref"] for it in items]
    by_ref = {it["ref"]: it for it in items}
    if not refs:
        return {}, {}

    nets = design.get("nets", []) or []
    aff = affinity_graph(design)

    # 初始布局：按亲和度排成一行多列（提供不错的起点）
    order = order_refs(refs, aff)
    cols = max(1, int(math.ceil(math.sqrt(len(order)))))
    pitch = max(max(by_ref[r]["w"], by_ref[r]["h"]) + 2.5 for r in refs)
    pos = {}
    for i, r in enumerate(order):
        pos[r] = (_snap(pitch * (i % cols), GRID_PCB),
                  _snap(pitch * (i // cols), GRID_PCB))
    # 中心化：后续越界惩罚以原点为中心，才好套用 target_w / target_h
    mx = sum(x for x, _ in pos.values()) / len(pos)
    my = sum(y for _, y in pos.values()) / len(pos)
    pos = {r: (_snap(x - mx, GRID_PCB), _snap(y - my, GRID_PCB))
           for r, (x, y) in pos.items()}

    def boxes(p):
        return {r: (p[r][0] - by_ref[r]["w"] / 2, p[r][1] - by_ref[r]["h"] / 2,
                    p[r][0] + by_ref[r]["w"] / 2, p[r][1] + by_ref[r]["h"] / 2)
                for r in refs}

    def cost(p):
        centers = dict(p)
        c = _hpwl(nets, centers)
        bxs = boxes(p)
        # 重叠（硬惩罚）
        ov = 0.0
        for i, a in enumerate(refs):
            for b in refs[i + 1:]:
                ov += _overlap_area(bxs[a], bxs[b])
        c += 12.0 * ov
        # 组连续性：同组元件质心应尽量聚在一起
        for g in design.get("groups", []) or []:
            gr = [r for r in (g.get("refs") or []) if r in p]
            if len(gr) > 1:
                gx = sum(p[r][0] for r in gr) / len(gr)
                gy = sum(p[r][1] for r in gr) / len(gr)
                c += 0.35 * sum(abs(p[r][0] - gx) + abs(p[r][1] - gy) for r in gr)
        # 越界惩罚（有目标尺寸时）
        if target_w and target_h:
            for r in refs:
                x, y = p[r]
                c += 8.0 * (max(0.0, abs(x) - target_w / 2) + max(0.0, abs(y) - target_h / 2))
        return c

    cur = dict(pos)
    cur_c = cost(cur)
    best, best_c = dict(cur), cur_c
    n = len(refs)

    for it in range(iterations):
        # 线性降温
        t = 3.0 * (1.0 - it / max(1, iterations)) + 0.02
        cand = dict(cur)
        if n >= 2 and rng.random() < 0.12:
            # 交换两个元件（帮助跳出局部最优）
            a, b = rng.sample(refs, 2)
            cand[a], cand[b] = cur[b], cur[a]
        else:
            r = rng.choice(refs)
            dx = _snap(rng.uniform(-pitch / 2, pitch / 2), GRID_PCB)
            dy = _snap(rng.uniform(-pitch / 2, pitch / 2), GRID_PCB)
            cand[r] = (_snap(cur[r][0] + dx, GRID_PCB),
                       _snap(cur[r][1] + dy, GRID_PCB))
        new_c = cost(cand)
        if new_c < cur_c or rng.random() < math.exp(min(0.0, (cur_c - new_c) / t)):
            cur, cur_c = cand, new_c
            if cur_c < best_c:
                best, best_c = dict(cur), cur_c

    # ---- 严格分离后处理：模拟退火允许软重叠换取更低线长，这里把仍然
    #      重叠的元件沿最小分离轴推开，直到 courtyard 完全不重叠。----
    gap = 0.6  # 封装之间额外留 0.6mm，供布线通道使用
    pos = dict(best)
    for _ in range(80):
        moved = False
        for i, a in enumerate(refs):
            for b in refs[i + 1:]:
                ax, ay = pos[a]
                bx, by = pos[b]
                dx_need = (by_ref[a]["w"] + by_ref[b]["w"]) / 2 + gap - abs(ax - bx)
                dy_need = (by_ref[a]["h"] + by_ref[b]["h"]) / 2 + gap - abs(ay - by)
                if dx_need > 0 and dy_need > 0:
                    # 沿重叠较小的轴推开
                    if dx_need < dy_need:
                        sign = 1.0 if ax <= bx else -1.0
                        shift = dx_need / 2 + 0.05
                        pos[a] = (ax - sign * shift, ay)
                        pos[b] = (bx + sign * shift, by)
                    else:
                        sign = 1.0 if ay <= by else -1.0
                        shift = dy_need / 2 + 0.05
                        pos[a] = (ax, ay - sign * shift)
                        pos[b] = (bx, by + sign * shift)
                    moved = True
        if not moved:
            break

    # 归一化到正坐标
    min_x = min(x for x, _ in pos.values())
    min_y = min(y for _, y in pos.values())
    out = {r: (_snap(pos[r][0] - min_x, GRID_PCB),
               _snap(pos[r][1] - min_y, GRID_PCB)) for r in refs}

    bxs = {r: (out[r][0] - by_ref[r]["w"] / 2, out[r][1] - by_ref[r]["h"] / 2,
               out[r][0] + by_ref[r]["w"] / 2, out[r][1] + by_ref[r]["h"] / 2)
           for r in refs}
    overlaps = sum(1 for i, a in enumerate(refs) for b in refs[i + 1:]
                   if _overlap_area(bxs[a], bxs[b]) > 0.01)
    metrics = {
        "algorithm": "simulated-annealing",
        "seed": seed,
        "iterations": iterations,
        "hpwl": round(_hpwl(nets, out), 2),
        "overlaps": overlaps,
        "cost": round(best_c, 2),
    }
    return out, metrics
