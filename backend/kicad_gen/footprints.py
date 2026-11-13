# -*- coding: utf-8 -*-
"""
KiCad 封装库读取与 s-expression 处理。

PCB 生成之前只写 Reference/Value 两个文本属性，完全没有 pad，所以在 KiCad
里打开是一片空白。本模块直接从本机 KiCad 安装目录的 ``share/kicad/footprints``
读取官方 ``.kicad_mod``，把真实封装（焊盘 / 丝印 / courtyard / 3D 模型）
内联进 .kicad_pcb。

设计要点：
  * 自带极简 s-expression 解析 / 序列化，不依赖第三方库；
  * 封装目录通过 kicad_detect 的安装根目录推导，找不到时退化为内置合成封装，
    保证没装 KiCad 的机器也能生成文件；
  * 尺寸用 courtyard 计算（没有 courtyard 时退化为焊盘 + 丝印包围盒）。
"""

from __future__ import annotations

import os
import re
import uuid

# ---------------------------------------------------------------- s-expression

class Atom(str):
    """未加引号的裸符号（roundrect / F.Cu / 0.5 ...）"""


class Str(str):
    """加引号的字符串"""


_UNESC = {"n": "\n", "t": "\t", "r": "\r", '"': '"', "\\": "\\"}


def parse(text):
    """把 s-expression 文本解析成嵌套 list；裸符号为 Atom，字符串为 Str。"""
    root = []
    stack = [root]
    cur = root
    i, n = 0, len(text)
    while i < n:
        ch = text[i]
        if ch in " \t\r\n":
            i += 1
        elif ch == "(":
            node = []
            cur.append(node)
            stack.append(node)
            cur = node
            i += 1
        elif ch == ")":
            if len(stack) > 1:
                stack.pop()
                cur = stack[-1]
            i += 1
        elif ch == '"':
            buf = []
            j = i + 1
            while j < n:
                c = text[j]
                if c == "\\" and j + 1 < n:
                    buf.append(_UNESC.get(text[j + 1], text[j + 1]))
                    j += 2
                    continue
                if c == '"':
                    break
                buf.append(c)
                j += 1
            cur.append(Str("".join(buf)))
            i = j + 1
        else:
            j = i
            while j < n and text[j] not in ' \t\r\n()"':
                j += 1
            cur.append(Atom(text[i:j]))
            i = j
    return root[0] if root else []


def _esc(s):
    return str(s).replace("\\", "\\\\").replace('"', '\\"')


def dump(node, indent=0):
    """序列化成 KiCad 风格（有子节点就换行缩进）。"""
    pad = "  " * indent
    if not isinstance(node, list):
        return '"%s"' % _esc(node) if isinstance(node, Str) else str(node)
    head, k = [], 0
    while k < len(node) and not isinstance(node[k], list):
        head.append(dump(node[k]))
        k += 1
    children = node[k:]
    if not children:
        return "(" + " ".join(head) + ")"
    if all(not isinstance(c, list) or all(not isinstance(x, list) for x in c) for c in children):
        return "(" + " ".join(head + [dump(c) for c in children]) + ")"
    out = ["(" + (" ".join(head) if head else "")]
    for c in children:
        out.append("  " * (indent + 1) + dump(c, indent + 1))
    return "\n".join(out) + "\n" + pad + ")"


def _u():
    return str(uuid.uuid4())


def _child(node, name):
    for c in node:
        if isinstance(c, list) and c and isinstance(c[0], str) and c[0] == name:
            return c
    return None


def _children(node, name):
    return [c for c in node if isinstance(c, list) and c and c[0] == name]


def _num(node, idx, default=0.0):
    try:
        return float(node[idx])
    except (TypeError, IndexError, ValueError):
        return default


# ---------------------------------------------------------------- 库定位

_FP_CACHE: dict[str, list | None] = {}


def _candidate_roots():
    """候选的 share/kicad 目录（含 footprints / symbols）"""
    roots = []
    try:
        from .. import kicad_detect  # type: ignore

        info = kicad_detect.detect()
        path = info.get("path") or ""
        # <root>/bin/kicad.exe -> <root>/share/kicad/footprints
        if path:
            bin_dir = os.path.dirname(path)
            root = os.path.dirname(bin_dir)
            roots.append(os.path.join(root, "share", "kicad", "footprints"))
    except Exception:  # noqa: BLE001
        pass
    for base in ("C:/Program Files/KiCad", "C:/Program Files (x86)/KiCad", "D:/KiCad", "E:/KiCad"):
        if os.path.isdir(base):
            for ver in sorted(os.listdir(base), reverse=True):
                roots.append(os.path.join(base, ver, "share", "kicad", "footprints"))
    roots.append(os.path.join(os.path.expanduser("~"), "Documents", "KiCad", "footprints"))
    return [r for r in roots if r]


_DIR_CACHE: list = []


def find_footprint_dir():
    """封装库根目录。命中后缓存；没找到时不缓存，便于用户设置 KiCad 路径后立即生效。"""
    if _DIR_CACHE:
        return _DIR_CACHE[0]
    for r in _candidate_roots():
        if os.path.isdir(r) and any(x.endswith(".pretty") for x in os.listdir(r)):
            _DIR_CACHE.append(r)
            return r
    return None


def clear_cache():
    _DIR_CACHE.clear()
    _FP_CACHE.clear()
    _FUZZY_CACHE.clear()


def available_libraries():
    d = find_footprint_dir()
    if not d:
        return []
    return sorted(x[: -len(".pretty")] for x in os.listdir(d) if x.endswith(".pretty"))


def load_footprint(lib_id):
    """'Resistor_SMD:R_0805_2012Metric' -> 解析后的 s-expression 节点；失败返回 None"""
    if not lib_id or ":" not in lib_id:
        return None
    if lib_id in _FP_CACHE:
        return _FP_CACHE[lib_id]
    lib, name = lib_id.split(":", 1)
    node = None
    base = find_footprint_dir()
    if base:
        p = os.path.join(base, lib + ".pretty", name + ".kicad_mod")
        if os.path.isfile(p):
            try:
                with open(p, encoding="utf-8", errors="replace") as f:
                    parsed = parse(f.read())
                if isinstance(parsed, list) and parsed and parsed[0] == "footprint":
                    node = parsed
            except Exception:  # noqa: BLE001
                node = None
    _FP_CACHE[lib_id] = node
    return node


_FUZZY_CACHE: dict[str, str | None] = {}


def resolve(rp: str, npins: int = 0) -> str | None:
    """把设计里的封装名解析到真实存在的库封装，返回 'Lib:Name' 或 None"""
    if not rp:
        return None
    if load_footprint(rp):
        return rp
    if rp in _FUZZY_CACHE:
        return _FUZZY_CACHE[rp]
    lib = rp.split(":", 1)[0] if ":" in rp else ""
    name = rp.split(":", 1)[1] if ":" in rp else rp
    base = find_footprint_dir()
    best = None
    if base and os.path.isdir(os.path.join(base, lib + ".pretty")):
        d = os.path.join(base, lib + ".pretty")
        cands = [x[: -len(".kicad_mod")] for x in os.listdir(d) if x.endswith(".kicad_mod")]
        # 同库：优先同名/前缀匹配，其次按管脚数匹配最常见的
        low = name.lower()
        hits = [c for c in cands if c.lower() == low]
        if not hits:
            hits = [c for c in cands if low in c.lower() or c.lower() in low]
        if hits:
            best = lib + ":" + sorted(hits, key=len)[0]
    _FUZZY_CACHE[rp] = best
    return best


# ---------------------------------------------------------------- 尺寸

def _rect_extent(node, acc):
    s, e = _child(node, "start"), _child(node, "end")
    if s and e:
        acc.append((_num(s, 1), _num(s, 2)))
        acc.append((_num(e, 1), _num(e, 2)))


def footprint_extent(fp):
    """返回封装在自身坐标系下的 (minx, miny, maxx, maxy)。

    优先用 courtyard（F.CrtYd）—— 这是 KiCad 判定元件占位的标准图层；
    没有时退化为焊盘 + 丝印。
    """
    def collect(layers):
        pts = []
        for ch in fp:
            if not isinstance(ch, list) or not ch:
                continue
            lay = _child(ch, "layer")
            lay_s = str(lay[1]) if lay and len(lay) > 1 else ""
            if lay_s not in layers:
                continue
            if ch[0] in ("fp_rect", "fp_line"):
                _rect_extent(ch, pts)
            elif ch[0] == "fp_circle":
                c = _child(ch, "center")
                e = _child(ch, "end")
                if c and e:
                    cx, cy = _num(c, 1), _num(c, 2)
                    r = max(abs(_num(e, 1) - cx), abs(_num(e, 2) - cy))
                    pts += [(cx - r, cy - r), (cx + r, cy + r)]
            elif ch[0] == "fp_arc":
                _rect_extent(ch, pts)
                for nm in ("mid",):
                    m = _child(ch, nm)
                    if m:
                        pts.append((_num(m, 1), _num(m, 2)))
        if not pts:
            return None
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        return (min(xs), min(ys), max(xs), max(ys))

    box = collect(("F.CrtYd",))
    if box:
        return box

    pts = []
    for pad in _children(fp, "pad"):
        at = _child(pad, "at")
        size = _child(pad, "size")
        if not at or not size:
            continue
        px, py = _num(at, 1), _num(at, 2)
        ang = _num(at, 3)
        w, h = _num(size, 1), _num(size, 2)
        if abs(ang % 180 - 90) < 5:
            w, h = h, w
        pts += [(px - w / 2, py - h / 2), (px + w / 2, py + h / 2)]
    box = collect(("F.SilkS", "F.Fab"))
    if box:
        pts += [(box[0], box[1]), (box[2], box[3])]
    if not pts:
        return (-2.5, -2.5, 2.5, 2.5)
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    return (min(xs), min(ys), max(xs), max(ys))


# ---------------------------------------------------------------- 合成封装（无 KiCad 时兜底）

def synthetic_footprint(lib_id, npins, smd=True):
    """按管脚数造一个规整封装：双列焊盘 + 丝印框 + courtyard。"""
    npins = max(int(npins or 2), 2)
    per_row = (npins + 1) // 2 if npins > 2 else 2
    pitch = 2.54 if not smd else 1.27
    pad_w, pad_h = (1.6, 1.6) if not smd else (0.7, 1.4)
    row_gap = max(per_row * pitch * 0.0 + (7.6 if not smd else 5.0), 4.0)
    body_w = max((per_row - 1) * pitch + pad_w + 1.6, 4.0)
    body_h = row_gap + 1.6
    half_w, half_h = body_w / 2, body_h / 2

    fp = [Atom("footprint"), Str(lib_id)]
    fp += [[Atom("layer"), Str("F.Cu")]]
    fp += [[Atom("descr"), Str("synthetic fallback footprint")]]
    fp += [[Atom("attr"), Atom("smd" if smd else "through_hole")]]
    # 丝印框
    for (sx, sy, ex, ey) in (
        (-half_w, -half_h, half_w, -half_h),
        (half_w, -half_h, half_w, half_h),
        (half_w, half_h, -half_w, half_h),
        (-half_w, half_h, -half_w, -half_h),
    ):
        fp.append([
            Atom("fp_line"),
            [Atom("start"), Atom(_fmt(sx)), Atom(_fmt(sy))],
            [Atom("end"), Atom(_fmt(ex)), Atom(_fmt(ey))],
            [Atom("stroke"), [Atom("width"), Atom("0.12")], [Atom("type"), Atom("solid")]],
            [Atom("layer"), Str("F.SilkS")],
        ])
    fp.append([
        Atom("fp_rect"),
        [Atom("start"), Atom(_fmt(-half_w - 0.25)), Atom(_fmt(-half_h - 0.25))],
        [Atom("end"), Atom(_fmt(half_w + 0.25)), Atom(_fmt(half_h + 0.25))],
        [Atom("stroke"), [Atom("width"), Atom("0.05")], [Atom("type"), Atom("solid")]],
        [Atom("fill"), Atom("no")],
        [Atom("layer"), Str("F.CrtYd")],
    ])
    fp.append([
        Atom("property"), Str("Reference"), Str("REF**"),
        [Atom("at"), Atom("0"), Atom(_fmt(-half_h - 1.6)), Atom("0")],
        [Atom("layer"), Str("F.SilkS")],
        [Atom("effects"), [Atom("font"), [Atom("size"), Atom("1"), Atom("1")], [Atom("thickness"), Atom("0.15")]]],
    ])
    fp.append([
        Atom("property"), Str("Value"), Str(lib_id),
        [Atom("at"), Atom("0"), Atom(_fmt(half_h + 1.6)), Atom("0")],
        [Atom("layer"), Str("F.Fab")],
        [Atom("effects"), [Atom("font"), [Atom("size"), Atom("1"), Atom("1")], [Atom("thickness"), Atom("0.15")]]],
    ])
    for i in range(npins):
        row = i % 2
        col = i // 2
        px = -((per_row - 1) * pitch) / 2 + col * pitch
        py = (-row_gap / 2) if row == 0 else (row_gap / 2)
        fp.append([
            Atom("pad"), Str(str(i + 1)), Atom("smd" if smd else "thru_hole"),
            Atom("rect") if not smd else Atom("roundrect"),
            [Atom("at"), Atom(_fmt(px)), Atom(_fmt(py))],
            [Atom("size"), Atom(_fmt(pad_w)), Atom(_fmt(pad_h))],
            [Atom("layers"), Str("F.Cu"), Str("F.Mask"), Str("F.Paste")]
            if smd else [Atom("layers"), Str("*.Cu"), Str("*.Mask")],
            [Atom("drill"), Atom("0.8")] if not smd else [Atom("roundrect_rratio"), Atom("0.25")],
        ])
    return fp


def _fmt(v):
    if abs(v - round(v)) < 1e-9:
        return str(int(round(v)))
    return f"{v:.3f}".rstrip("0").rstrip(".")
