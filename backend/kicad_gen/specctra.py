# -*- coding: utf-8 -*-
"""Specctra DSN 导出 / SES 导入（v2.3）

让 Freerouting 接手布线：
  * export_dsn(design, pcb_text) —— 从 .kicad_pcb 解析封装/焊盘/网络/板框，
    写成 Freerouting v2.5 官方格式的 Specctra .dsn。
  * merge_ses(pcb_text, ses_text) —— 把 .ses 里的 wire/via 转成 KiCad
    segment/via，合并回原 PCB。

为什么不用 kicad-cli：KiCad 10 的 Specctra DSN/SES 导入导出只能在 PCB
编辑器 GUI 菜单里操作，CLI 不支持。所以这里直接读写 s-expression。

格式对照 freerouting/freerouting fixtures/*.dsn（resolution um 10，
即 1 内部单位 = 0.1µm；KiCad mm × 1000 / 10 = mm × 100）。
"""

from __future__ import annotations

import math
import os
import uuid

from . import footprints as fplib

# 官方样例里 2mm 焊盘 = rect -1000..1000，证明 1 DSN unit = 1µm。
# (resolution um 10) 中的 10 是 Freerouting 的显示精度参数，不是单位换算因子。
UNITS_PER_MM = 1000.0


def _u():
    return str(uuid.uuid4())


def _f(v):
    v = round(float(v), 4)
    return str(int(v)) if abs(v - round(v)) < 1e-9 else ("%.4f" % v).rstrip("0").rstrip(".")


def _dsn(v_mm):
    """KiCad mm → DSN 单位（1 unit = 1µm）"""
    return _f(float(v_mm) * UNITS_PER_MM)


def _dsn_to_mm(v):
    """DSN 单位 → KiCad mm"""
    return float(v) / UNITS_PER_MM


def _esc(s):
    s = str(s or "")
    if any(ch in s for ch in ' ()"'):
        return '"%s"' % s.replace('"', '\\"')
    return s


# ---------------------------------------------------------------- 解析 PCB

def _find_nodes(node, tag):
    return [c for c in (node or []) if isinstance(c, list) and c and str(c[0]) == tag]


def _first(node, tag):
    r = _find_nodes(node, tag)
    return r[0] if r else None


def _vals(group):
    return [str(x) for x in group[1:] if not isinstance(x, list)]


def _parse_pcb(pcb_text):
    """解析 .kicad_pcb，抽取网络名 / 封装实例 / 板框。"""
    tree = fplib.parse(pcb_text)
    nets = {}
    for n in _find_nodes(tree, "net"):
        v = _vals(n)
        if len(v) >= 2:
            nets[int(v[0])] = v[1]

    footprints, outline = [], []
    for fp in _find_nodes(tree, "footprint"):
        lib_id = str(fp[1]) if len(fp) > 1 else "?"
        at = _first(fp, "at")
        av = _vals(at) if at else ["0", "0", "0"]
        x, y = float(av[0]), float(av[1])
        rot = float(av[2]) if len(av) > 2 else 0.0
        ref = val = ""
        pads = []
        for prop in _find_nodes(fp, "property"):
            pv = _vals(prop)
            if pv and pv[0] == "Reference" and len(pv) > 1:
                ref = pv[1]
            elif pv and pv[0] == "Value" and len(pv) > 1:
                val = pv[1]
        for pad in _find_nodes(fp, "pad"):
            pv = _vals(pad)
            pin = pv[0] if pv else "?"
            pat = _first(pad, "at")
            psize = _first(pad, "size")
            pnet = _first(pad, "net")
            pdrill = _first(pad, "drill")
            p_av = _vals(pat) if pat else ["0", "0"]
            p_sv = _vals(psize) if psize else ["1.6", "1.6"]
            net_id = int(_vals(pnet)[0]) if pnet and _vals(pnet) else 0
            rad = math.radians(rot)
            lx, ly = float(p_av[0]), float(p_av[1])
            # KiCad: y 轴向下 + 角度逆时针 → (lx,ly)→(lx·cos+ly·sin, -lx·sin+ly·cos)
            # rot=90 时 (0,2.54) 应落在 (x+2.54, y)，不是 (x-2.54, y)
            wx = x + lx * math.cos(rad) + ly * math.sin(rad)
            wy = y - lx * math.sin(rad) + ly * math.cos(rad)
            w, h = float(p_sv[0]), float(p_sv[1])
            pads.append({"pin": pin, "x": wx, "y": wy, "w": w, "h": h,
                         "net": net_id, "th": pdrill is not None})
        footprints.append({"ref": ref or lib_id, "value": val, "lib": lib_id,
                           "x": x, "y": y, "rot": rot, "pads": pads})

    for tag in ("gr_line", "gr_arc", "gr_rect"):
        for seg in _find_nodes(tree, tag):
            layer = _first(seg, "layer")
            if not layer or "Edge.Cuts" not in str(layer[1] if len(layer) > 1 else ""):
                continue
            for t in ("start", "end", "mid"):
                g = _first(seg, t)
                if g:
                    v = _vals(g)
                    if len(v) >= 2:
                        outline.append((float(v[0]), float(v[1])))
    return nets, footprints, outline


# ---------------------------------------------------------------- DSN 导出

def export_dsn(design, pcb_text):
    """生成 Specctra DSN 文本（Freerouting v2.5 官方格式）。返回 (dsn, stats)。"""
    nets, fps, outline = _parse_pcb(pcb_text)
    if not fps:
        raise ValueError("PCB 中没有封装，无法导出 DSN")
    if len(outline) < 3:
        raise ValueError("PCB 中没有板框，无需布线")

    title = _esc(design.get("title") or "eda_agent").replace(" ", "_")

    xs = [p[0] for p in outline]
    ys = [p[1] for p in outline]
    x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)

    L = []
    L.append("(pcb %s" % title)
    L.append('  (parser (string_quote ") (space_in_quoted_tokens on) '
             '(host_cad "EDA Agent") (host_version "2.3") )')
    L.append("  (resolution um 10)")
    L.append("  (unit um)")
    L.append("  (structure")
    L.append("    (layer F.Cu (type signal) (property (index 0) ) )")
    L.append("    (layer B.Cu (type signal) (property (index 1) ) )")
    bp = " ".join(_dsn(v) for v in (x0, y0, x1, y0, x1, y1, x0, y1, x0, y0))
    L.append("    (boundary (path pcb 0 %s) )" % bp)
    L.append('    (via "Via[0-1]_800:400_um")')
    L.append("    (rule (width 250) (clearance 250) )")
    L.append("  )")

    # 每个封装实例用独立 image，pin 坐标直接烘焙实例的旋转（place 一律 rot=0）。
    # 这样绕开 Freerouting(数学坐标/y向上) 与 KiCad(y向下) 的旋转约定差异。
    images = {}
    padstacks = {}
    net_pins = {}

    for fp in fps:
        ref = fp["ref"]
        lib = fp["lib"]
        pn = fp["value"] or lib.split(":")[-1]
        img_name = "IMG_" + _esc(ref)
        img = {"lib": lib, "ref": ref, "x": fp["x"], "y": fp["y"],
               "pn": pn, "pins": [], "minx": 0.0, "maxx": 0.0,
               "miny": 0.0, "maxy": 0.0}
        for pad in fp["pads"]:
            # pin 相对 place 原点的偏移，已含旋转 → 无需 Freerouting 再旋转
            lx, ly = pad["x"] - fp["x"], pad["y"] - fp["y"]
            try:
                margin = float(os.environ.get("FREEROUTE_MARGIN", "0.6"))
            except ValueError:
                margin = 0.6
            w, h = pad["w"] + margin, pad["h"] + margin
            pname = "P_%sx%s%s" % (_f(w * UNITS_PER_MM), _f(h * UNITS_PER_MM),
                                   "" if pad["th"] else "s")
            padstacks[pname] = (w, h, pad["th"])
            img["pins"].append((pname, pad["pin"], lx, ly))
            img["minx"] = min(img["minx"], lx - w / 2)
            img["maxx"] = max(img["maxx"], lx + w / 2)
            img["miny"] = min(img["miny"], ly - h / 2)
            img["maxy"] = max(img["maxy"], ly + h / 2)
            pin_ref = _esc(ref) + "-" + _esc(pad["pin"])
            if pad["net"] > 0:
                nname = _esc(nets.get(pad["net"], "N%d" % pad["net"]))
            else:
                nname = "unconnected-%s-%s" % (_esc(ref), _esc(pad["pin"]))
            net_pins.setdefault(nname, []).append(pin_ref)
        images[img_name] = img

    L.append("  (placement")
    for img_name, img in images.items():
        L.append("    (component %s" % img_name)
        L.append("      (place %s %s %s front 0 (PN %s) )"
                 % (_esc(img["ref"]), _dsn(img["x"]), _dsn(img["y"]), _esc(img["pn"])))
        L.append("    )")
    L.append("  )")

    L.append("  (library")
    for img_name, img in images.items():
        L.append("    (image %s" % img_name)
        a1, b1 = _dsn(img["minx"] - 0.5), _dsn(img["miny"] - 0.5)
        c1, d1 = _dsn(img["maxx"] + 0.5), _dsn(img["maxy"] + 0.5)
        L.append("      (outline (polygon signal 0 %s %s %s %s %s %s %s %s))"
                 % (a1, b1, c1, b1, c1, d1, a1, d1))
        for pname, pin, lx, ly in img["pins"]:
            L.append("      (pin %s %s %s %s)" % (_esc(pname), _esc(pin), _dsn(lx), _dsn(ly)))
        L.append("    )")
    for pname, (w, h, th) in padstacks.items():
        hx = _f(w / 2 * UNITS_PER_MM)
        hy = _f(h / 2 * UNITS_PER_MM)
        nx = _f(-w / 2 * UNITS_PER_MM)
        ny = _f(-h / 2 * UNITS_PER_MM)
        L.append("    (padstack %s" % _esc(pname))
        L.append("      (shape (rect F.Cu %s %s %s %s))" % (nx, ny, hx, hy))
        if th:
            L.append("      (shape (rect B.Cu %s %s %s %s))" % (nx, ny, hx, hy))
        L.append("      (attach off)")
        L.append("    )")
    L.append('    (padstack "Via[0-1]_800:400_um"')
    L.append("      (shape (circle F.Cu 400))")
    L.append("      (shape (circle B.Cu 400))")
    L.append("      (attach off)")
    L.append("    )")
    L.append("  )")

    L.append("  (network")
    for nname, pins in sorted(net_pins.items()):
        L.append("    (net %s (pins %s) )" % (nname, " ".join(pins)))
    class_nets = " ".join(sorted(net_pins.keys()))
    if class_nets:
        L.append("    (class default %s)" % class_nets)
    L.append("  )")
    L += ["  (wiring", "  )", ")"]

    stats = {"components": len(fps),
             "pads": sum(len(fp["pads"]) for fp in fps),
             "nets": len(net_pins),
             "board_mm": [_f(x0), _f(y0), _f(x1), _f(y1)]}
    return "\n".join(L) + "\n", stats


# ---------------------------------------------------------------- SES 导入

def _ses_to_mm(v):
    """SES routes 坐标：resolution um 10 → 1 unit = 0.1µm → mm = v/10000"""
    return float(v) / 10000.0


def _reparse_ses(ses_text):
    """从 SES 抽 wire/via。

    Freerouting SES 实际结构：
      (network_out
        (net GND
          (wire (path B.Cu 2500 x1 y1 x2 y2 ...))
          (via ...)
        )
      )
    网络名在外层 (net ...)，wire 内只有 (path <layer> <width> coords...)。
    """
    tree = fplib.parse(ses_text)
    wires, vias = [], []

    def find_all(node, tag):
        out = []
        if not isinstance(node, list):
            return out
        if node and str(node[0]) == tag:
            out.append(node)
        for c in node:
            if isinstance(c, list):
                out.extend(find_all(c, tag))
        return out

    # 按网络分组处理
    for net_node in find_all(tree, "net"):
        nv = _vals(net_node)
        net_name = nv[0] if nv else ""
        for wire in find_all(net_node, "wire"):
            for path in find_all(wire, "path"):
                pv = _vals(path)
                if len(pv) < 4:
                    continue
                layer_name = pv[0]
                try:
                    width = _ses_to_mm(pv[1])
                except ValueError:
                    width = 0.25
                pts = []
                for k in range(2, len(pv) - 1, 2):
                    try:
                        pts.append((_ses_to_mm(pv[k]), _ses_to_mm(pv[k + 1])))
                    except ValueError:
                        pass
                if pts:
                    layer = "B.Cu" if "B.Cu" in layer_name or "bottom" in layer_name.lower() else "F.Cu"
                    # Freerouting 会把个别密集走线自动收窄到 0.187mm，
                    # 低于 KiCad 默认最小线宽 0.2mm → clamp 避免 DRC track_width
                    width = max(0.2, min(width, 0.6))
                    wires.append({"pts": pts, "net": net_name, "w": width, "layer": layer})
        for via in find_all(net_node, "via"):
            # via 在 SES 里通常是 (via (at x y) (net ...)) 或 path 形式
            at = _first(via, "at")
            av = _vals(at) if at else []
            pv = []
            for path in find_all(via, "path"):
                pv = _vals(path)
                if len(pv) >= 2:
                    av = [pv[0], pv[1]]
                    break
            if len(av) >= 2:
                try:
                    vias.append({"x": _ses_to_mm(av[0]), "y": _ses_to_mm(av[1]),
                                 "net": net_name, "dia": 0.8, "drill": 0.4})
                except ValueError:
                    pass
    return wires, vias


def _seg_node(a, b, width, net_id, layer="F.Cu"):
    return [
        fplib.Atom("segment"),
        [fplib.Atom("start"), fplib.Atom(_f(a[0])), fplib.Atom(_f(a[1]))],
        [fplib.Atom("end"), fplib.Atom(_f(b[0])), fplib.Atom(_f(b[1]))],
        [fplib.Atom("width"), fplib.Atom(_f(width))],
        [fplib.Atom("layer"), fplib.Str(layer)],
        [fplib.Atom("net"), fplib.Atom(str(net_id))],
        [fplib.Atom("uuid"), fplib.Str(_u())],
    ]


def merge_ses(pcb_text, ses_text, design=None):
    """把 SES 走线合并回 .kicad_pcb。返回 (new_pcb_text, stats)。"""
    nets, _fps, _ = _parse_pcb(pcb_text)
    name_to_id = {v: k for k, v in nets.items()}
    wires, vias = _reparse_ses(ses_text)

    added, seg_count = [], 0
    for w in wires:
        nid = name_to_id.get(w["net"], 0)
        if not nid:
            continue
        pts = w["pts"]
        for a, b in zip(pts, pts[1:]):
            if abs(a[0] - b[0]) < 1e-6 and abs(a[1] - b[1]) < 1e-6:
                continue
            added.append(_seg_node(a, b, w["w"], nid, w.get("layer", "F.Cu")))
            seg_count += 1

    via_count = 0
    for v in vias:
        nid = name_to_id.get(v["net"], 0)
        if not nid:
            continue
        added.append([
            fplib.Atom("via"),
            [fplib.Atom("at"), fplib.Atom(_f(v["x"])), fplib.Atom(_f(v["y"]))],
            [fplib.Atom("size"), fplib.Atom(_f(v["dia"]))],
            [fplib.Atom("drill"), fplib.Atom(_f(v["drill"]))],
            [fplib.Atom("layers"), fplib.Str("F.Cu"), fplib.Str("B.Cu")],
            [fplib.Atom("net"), fplib.Atom(str(nid))],
            [fplib.Atom("uuid"), fplib.Str(_u())],
        ])
        via_count += 1

    if not added:
        return pcb_text, {"segments": 0, "vias": 0, "note": "SES 中没有可导入的走线"}

    idx = pcb_text.rfind(")")
    addition = "\n".join("  " + fplib.dump(n, 1) for n in added)
    new_text = pcb_text[:idx] + addition + "\n" + pcb_text[idx:]
    return new_text, {"segments": seg_count, "vias": via_count}
