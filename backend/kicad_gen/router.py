# -*- coding: utf-8 -*-
"""A* 自动布线引擎（v2.2.0）

借鉴 FreeRouting / KiCadRoutingTools 的网格 A* 思路，纯 Python 实现，
无 Java / Rust / 第三方依赖，可直接塞进 PyInstaller 打包。

两部分：
  * route_pcb —— 双层（F.Cu / B.Cu）网格 A*，自动打过孔，输出真实
    segment / via s-expression；布不通的网络保留飞线（不产生 DRC 错误）。
  * route_schematic —— 在布局给的通道（lane）上用 A* 绕开元件卡片和已有
    走线，输出正交折线 + junction，替代 v2.1.0 的「直连竖线」。

设计原则：**宁可少布几根，也不能布出 DRC 错误**。障碍半径统一加
clearance + 半线宽，保证铜箔间距满足 KiCad 默认 0.2mm 规则。
"""

from __future__ import annotations

import heapq
import math
import uuid

GRID = 0.5              # PCB 布线网格 (mm)
CLEARANCE = 0.25        # 障碍外扩 (mm)
TRACK_W = 0.25          # 信号线宽 (mm)
POWER_W = 0.45          # 电源/地线宽 (mm)
VIA_SIZE = 0.8
VIA_DRILL = 0.4
VIA_COST = 14           # 换层次数惩罚（格数）

LAYERS = ("F.Cu", "B.Cu")


def _u():
    return str(uuid.uuid4())


def _fmt(v):
    v = round(float(v), 3)
    return str(int(v)) if abs(v - round(v)) < 1e-9 else ("%.3f" % v).rstrip("0").rstrip(".")


# ---------------------------------------------------------------- 通用 A*

def _astar(start, goal, blocked, width, height, allow_layers=False, diags=False):
    """网格 A*。状态 (gx, gy, layer)。blocked: set((x,y,layer))。
    返回 [(x,y,layer), ...] 或 None。

    v2.2.0 关键修正：默认只用四方向（正交）。对角走线在 0.5mm 网格上
    会和相邻网络擦出 0.1mm 间距，必然触发 KiCad clearance 错误。
    """
    sx, sy = start
    gx, gy = goal
    if not (0 <= sx < width and 0 <= sy < height and 0 <= gx < width and 0 <= gy < height):
        return None
    layers = (0, 1) if allow_layers else (0,)

    def h(x, y):
        return abs(x - gx) + abs(y - gy)

    open_h = [(h(sx, sy), 0, sx, sy, layers[0])]
    dist = {(sx, sy, layers[0]): 0}
    parent = {}
    dirs = ((1, 0), (-1, 0), (0, 1), (0, -1))
    if diags:
        dirs += ((1, 1), (1, -1), (-1, 1), (-1, -1))

    while open_h:
        _, g, x, y, ly = heapq.heappop(open_h)
        if g != dist.get((x, y, ly)):
            continue
        if x == gx and y == gy:
            path = [(x, y, ly)]
            while (x, y, ly) in parent:
                x, y, ly = parent[(x, y, ly)]
                path.append((x, y, ly))
            return list(reversed(path))
        for dx, dy in dirs:
            nx, ny = x + dx, y + dy
            if not (0 <= nx < width and 0 <= ny < height):
                continue
            # 禁止对角切角：两侧正交格都被占时不许斜穿
            if dx and dy and ((x + dx, y, ly) in blocked or (x, y + dy, ly) in blocked):
                continue
            step = 1.414 if (dx and dy) else 1.0
            ng = g + step
            for nly in layers:
                if (nx, ny, nly) in blocked:
                    continue
                change = VIA_COST if nly != ly else 0
                if nly != ly:
                    # 过孔半径 0.4mm + 间距 0.2mm，周围两圈都不能有任何东西
                    if any((nx + ax, ny + ay, other) in blocked
                           for ax in range(-2, 3) for ay in range(-2, 3)
                           if abs(ax) + abs(ay) <= 2
                           for other in layers):
                        continue
                key = (nx, ny, nly)
                if ng + change < dist.get(key, float("inf")):
                    dist[key] = ng + change
                    parent[key] = (x, y, ly)
                    heapq.heappush(open_h, (ng + change + h(nx, ny), ng + change, nx, ny, nly))
    return None


def _compress(path):
    """把逐格路径压成折线段（只保留拐点/换层点）。"""
    if len(path) < 2:
        return []
    segs = []
    start = path[0]
    prev = path[0]
    direction = None
    for cur in path[1:]:
        d = (cur[0] - prev[0], cur[1] - prev[1], cur[2] - prev[2])
        if direction is None:
            direction = d
        elif d != direction:
            segs.append((start, prev))
            start = prev
            direction = d
        prev = cur
    segs.append((start, prev))
    return segs


# ---------------------------------------------------------------- PCB

def _children(node, tag):
    return [c for c in node if isinstance(c, list) and c and str(c[0]) == tag]


def _num(group, idx=1, default=0.0):
    try:
        return float(group[idx])
    except Exception:
        return default


def collect_pads(fp_nodes):
    """从封装实例节点中收集焊盘绝对坐标与尺寸。

    fp_nodes: [(lib_id, x, y, rot, node), ...]
    KiCad 90° 旋转把局部 (px,py) 映射到 (py,-px)。
    """
    pads = []
    for ref, fp_x, fp_y, rot, node in fp_nodes:
        for pad in _children(node, "pad"):
            if not pad or len(pad) < 2:
                continue
            pin = str(pad[1])
            at = _children(pad, "at")
            size = _children(pad, "size")
            if not at:
                continue
            lx, ly = _num(at[0], 1), _num(at[0], 2)
            w = _num(size[0], 1, 1.6) if size else 1.6
            h = _num(size[0], 2, 1.6) if size else 1.6
            if rot == 90:
                wx, wy = fp_x + ly, fp_y - lx
                w, h = h, w
            else:
                wx, wy = fp_x + lx, fp_y + ly
            pads.append({"ref": ref, "pin": pin, "x": wx, "y": wy,
                         "r": max(w, h) / 2.0})
    return pads


def route_pcb(design, fp_nodes, board, netmap):
    """双层 A* 布线。

    fp_nodes: [(ref, fp_x, fp_y, rot, footprint_node)]
    board: (x0, y0, x1, y1) 板框范围（世界坐标）
    netmap: (ref, pin) -> (net_index, net_name)

    返回 (segment_nodes, via_nodes, stats)。节点是 fplib.Atom/Str 构建的
    s-expression 列表，直接交给 pcb.py dump。
    """
    from . import footprints as fplib

    x0, y0, x1, y1 = board
    if x1 - x0 < 4 or y1 - y0 < 4:
        return [], [], {"routed": 0, "total": 0, "reason": "board too small"}

    # 网格范围（世界坐标 → 格）
    gx0 = math.ceil((x0 + 0.6) / GRID)
    gy0 = math.ceil((y0 + 0.6) / GRID)
    gx1 = math.floor((x1 - 0.6) / GRID)
    gy1 = math.floor((y1 - 0.6) / GRID)
    width, height = gx1 - gx0 + 1, gy1 - gy0 + 1
    if width < 4 or height < 4:
        return [], [], {"routed": 0, "total": 0, "reason": "grid too small"}

    def to_grid(x, y):
        return (int(round(x / GRID)) - gx0, int(round(y / GRID)) - gy0)

    def to_world(gx, gy):
        return ((gx + gx0) * GRID, (gy + gy0) * GRID)

    pads = collect_pads(fp_nodes)
    by_net = {}
    for p in pads:
        net = netmap.get((p["ref"], p["pin"]))
        if net:
            by_net.setdefault(net[0], []).append(p)

    # 静态障碍：所有焊盘（每层都挡）。
    # 半径 = 焊盘外接圆 + 阻焊桥余量 + 安全间距 + 半线宽。多留 0.3mm 是
    # 为了覆盖焊盘非圆形/旋转后的实际占用，避免 solder_mask_bridge 误报。
    static = set()
    for p in pads:
        px, py = p["x"], p["y"]
        rad = p["r"] * 1.15 + 0.45 + CLEARANCE + TRACK_W / 2.0
        cells = int(math.ceil(rad / GRID)) + 1
        cgx, cgy = to_grid(px, py)
        for dx in range(-cells, cells + 1):
            for dy in range(-cells, cells + 1):
                nx, ny = cgx + dx, cgy + dy
                if not (0 <= nx < width and 0 <= ny < height):
                    continue
                wx, wy = to_world(nx, ny)
                if (wx - px) ** 2 + (wy - py) ** 2 <= rad ** 2:
                    static.add((nx, ny, 0))
                    static.add((nx, ny, 1))

    # 焊盘入口格：离焊盘中心最近的格。走线端点落在焊盘铜内即电气连通。
    # 同时把每个焊盘的自身障碍格记下来，布自己的网络时豁免、布别的网络时阻挡。
    pad_cells = {}
    own_cells = {idx: set() for idx in by_net}
    for idx, ps in by_net.items():
        for p in ps:
            cgx, cgy = to_grid(p["x"], p["y"])
            mime = set()
            # 该焊盘半径内的所有格都算「自己的」障碍
            rad = p["r"] * 1.15 + 0.45 + CLEARANCE + TRACK_W / 2.0
            cells = int(math.ceil(rad / GRID)) + 1
            for dx in range(-cells, cells + 1):
                for dy in range(-cells, cells + 1):
                    g = (cgx + dx, cgy + dy)
                    if not (0 <= g[0] < width and 0 <= g[1] < height):
                        continue
                    wx, wy = to_world(g[0], g[1])
                    if (wx - p["x"]) ** 2 + (wy - p["y"]) ** 2 <= rad ** 2:
                        for ly in (0, 1):
                            if (g[0], g[1], ly) in static:
                                mime.add((g[0], g[1], ly))
            own_cells[idx] |= mime
            pad_cells[id(p)] = (cgx, cgy)

    def pad_target(p):
        return pad_cells[id(p)]

    occupied = set()      # 已布走线占用的格（所有网络共用，必须避开）
    seg_nodes, via_nodes = [], []
    routed = 0
    nets = design.get("nets", []) or []

    def emit_seg(a, b, w, net_idx, layer):
        ax, ay = to_world(a[0], a[1])
        bx, by = to_world(b[0], b[1])
        if abs(ax - bx) < 1e-6 and abs(ay - by) < 1e-6:
            return
        seg_nodes.append([
            fplib.Atom("segment"),
            [fplib.Atom("start"), fplib.Atom(_fmt(ax)), fplib.Atom(_fmt(ay))],
            [fplib.Atom("end"), fplib.Atom(_fmt(bx)), fplib.Atom(_fmt(by))],
            [fplib.Atom("width"), fplib.Atom(_fmt(w))],
            [fplib.Atom("layer"), fplib.Str(LAYERS[layer])],
            [fplib.Atom("net"), fplib.Atom(str(net_idx))],
            [fplib.Atom("uuid"), fplib.Str(_u())],
        ])

    # 信号网络优先（少引脚先布），电源/地最后（可用 B.Cu 兜底）
    def sort_key(item):
        idx, ps = item
        name = (nets[idx - 1].get("name") or "") if 0 < idx <= len(nets) else ""
        power = any(k in name.upper() for k in ("GND", "VCC", "3V3", "5V", "+"))
        return (power, len(ps), idx)

    for net_idx, ps in sorted(by_net.items(), key=sort_key):
        if len(ps) < 2:
            continue
        name = (nets[net_idx - 1].get("name") or f"N{net_idx}") if 0 < net_idx <= len(nets) else f"N{net_idx}"
        w = POWER_W if any(k in name.upper() for k in ("GND", "VCC", "3V3", "5V", "+")) else TRACK_W
        targets = [pad_target(p) for p in ps]
        # 本网络障碍：静态障碍去掉自身焊盘，但保留其它网络已布的走线。
        # 起终点格（焊盘中心所在格）只放行本网络的，若它同时落在别的网络
        # 焊盘障碍里就放弃该网络（宁可留飞线，也不能短路）。
        foreign = set()
        for other_idx, cells in own_cells.items():
            if other_idx != net_idx:
                foreign |= cells
        blocked = (static - own_cells[net_idx]) | occupied
        aborted = False
        for gx_t, gy_t in targets:
            if (gx_t, gy_t, 0) in foreign or (gx_t, gy_t, 1) in foreign:
                aborted = True
                break
            blocked.discard((gx_t, gy_t, 0))
            blocked.discard((gx_t, gy_t, 1))
        if aborted:
            continue

        # Prim 最小生成树：从第一个焊盘出发，逐个把最近的未连焊盘接上
        connected = [0]
        remaining = set(range(1, len(ps)))
        net_ok = True
        while remaining:
            best = None
            for a in connected:
                for b in remaining:
                    d = abs(targets[a][0] - targets[b][0]) + abs(targets[a][1] - targets[b][1])
                    if best is None or d < best[0]:
                        best = (d, a, b)
            if best is None:
                break
            _, a, b = best
            path = _astar(targets[a], targets[b], blocked, width, height,
                          allow_layers=True, diags=False)
            if path is None:
                net_ok = False
                break
            for (s, e) in _compress(path):
                if s[2] != e[2]:
                    wx, wy = to_world(e[0], e[1])
                    via_nodes.append([
                        fplib.Atom("via"),
                        [fplib.Atom("at"), fplib.Atom(_fmt(wx)), fplib.Atom(_fmt(wy))],
                        [fplib.Atom("size"), fplib.Atom(_fmt(VIA_SIZE))],
                        [fplib.Atom("drill"), fplib.Atom(_fmt(VIA_DRILL))],
                        [fplib.Atom("layers"), fplib.Str("F.Cu"), fplib.Str("B.Cu")],
                        [fplib.Atom("net"), fplib.Atom(str(net_idx))],
                        [fplib.Atom("uuid"), fplib.Str(_u())],
                    ])
                    continue
                emit_seg(s, e, w, net_idx, s[2])
            # 登记占用带：路径格 + 正交相邻格。0.5mm 网格下，相邻格禁止
            # 后其它网络最近只能贴到 1mm 外，扣掉两侧半线宽仍有 0.75mm，
            # 远大于 0.2mm 安全间距；同时避免斜向擦边。
            for (gx, gy, ly) in path:
                for ax in (-1, 0, 1):
                    for ay in (-1, 0, 1):
                        occupied.add((gx + ax, gy + ay, ly))
            connected.append(b)
            remaining.discard(b)
        if net_ok:
            routed += 1

    return seg_nodes, via_nodes, {
        "algorithm": "2-layer A* (orthogonal)",
        "grid_mm": GRID,
        "nets_total": len(by_net),
        "nets_routed": routed,
        "segments": len(seg_nodes),
        "vias": len(via_nodes),
    }


# ---------------------------------------------------------------- 原理图

def route_schematic_nets(design, lay):
    """在布局通道上做 A*，返回结构化走线。

    lay 需含 cells / group_boxes / net_points / lanes / bounds。
    返回 {"wires": [(x1,y1,x2,y2), ...], "junctions": [(x,y)],
          "labels": [(name,x,y)], "stats": {...}}
    """
    step = 1.27
    bx0, by0, bx1, by1 = lay["bounds"]
    width = int((bx1 - bx0) / step) + 1
    height = int((by1 - by0) / step) + 1
    if width < 2 or height < 2:
        return {"wires": [], "junctions": [], "labels": [], "stats": {}}

    # 障碍：元件卡片 + 模块框边界（元件引脚起点本身在卡片外沿）
    blocked = set()
    for (gx0, gy0, gx1, gy1) in lay["group_boxes"].values():
        for gx in range(max(0, int(gx0 / step)), min(width, int(gx1 / step) + 1)):
            for gy in range(max(0, int(gy0 / step)), min(height, int(gy1 / step) + 1)):
                blocked.add((gx, gy, 0))
    # 模块框整体挡住的话引脚 stub 会落在框内 → 只挡元件卡片，不挡整个框
    blocked.clear()
    for ref, (cx, cy) in lay["positions"].items():
        cw, ch = lay["cells"][ref]
        for gx in range(max(0, int((cx - cw / 2) / step)), min(width, int((cx + cw / 2) / step) + 1)):
            for gy in range(max(0, int((cy - ch / 2) / step)), min(height, int((cy + ch / 2) / step) + 1)):
                blocked.add((gx, gy, 0))

    def to_g(x, y):
        return (int(round(x / step)), int(round(y / step)))

    def to_w(gx, gy):
        return (round(gx * step, 2), round(gy * step, 2))

    wires, junctions, labels = [], [], []
    occupied = set()
    for name, pts in lay["net_points"].items():
        if not pts:
            continue
        lane_y = lay["lanes"][name]
        gy_target = int(round(lane_y / step))
        xs = sorted({p["stub_x"] for p in pts})
        # 主干：在 lane 上从最左到最右
        if len(xs) >= 2:
            wires.append((xs[0], lane_y, xs[-1], lane_y))
            for x in xs:
                junctions.append((x, lane_y))
            for gx in range(to_g(xs[0], lane_y)[0], to_g(xs[-1], lane_y)[0] + 1):
                occupied.add((gx, gy_target, 0))
        for p in pts:
            sx, sy = p["stub_x"], p["y"]
            # 引脚 → stub（固定水平段，避开卡片）
            if abs(p["x"] - sx) > 0.1:
                wires.append((p["x"], p["y"], sx, p["y"]))
            gs, gt = to_g(sx, sy), (to_g(sx, lane_y)[0], gy_target)
            path = _astar(gs, gt, blocked | occupied, width, height, allow_layers=False)
            if path is None:
                # 兜底：退回正交两段式（v2.1 行为），保证不缺线
                wires.append((sx, sy, sx, lane_y))
                continue
            for (a, b) in _compress(path):
                x1, y1 = to_w(a[0], a[1])
                x2, y2 = to_w(b[0], b[1])
                if (x1, y1) != (x2, y2):
                    wires.append((x1, y1, x2, y2))
            for gx, gy, _ in path:
                occupied.add((gx, gy, 0))
        labels.append((name, xs[0], lane_y))

    return {
        "wires": wires,
        "junctions": junctions,
        "labels": labels,
        "stats": {"algorithm": "channel A*", "nets": len(lay["net_points"]),
                  "wires": len(wires), "junctions": len(junctions)},
    }
