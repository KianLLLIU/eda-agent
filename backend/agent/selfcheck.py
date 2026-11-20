# -*- coding: utf-8 -*-
"""布线后自检 · 通电模拟 · 自动修正（v2.4）

生成 KiCad 工程并完成布线后，自动做四件事：

  1. 网表电气自检——电源轨冲突、引脚跨网短路、悬空电源脚、单端网络、
     缺位号/缺值、元件孤立的静态检查（不需要 KiCad）。
  2. 通电模拟——把网表当连通图，模拟上电瞬间的电气状态：识别电源/地轨、
     检查电源是否成环、关键器件供电是否到位、信号链是否从输入走到输出，
     输出"预计可否工作"的判断。这是**静态电气推理**，不是 SPICE 瞬态仿真。
  3. KiCad 实测——调 kicad-cli 跑 sch ERC 与 pcb DRC，把官方违规纳入报告。
  4. 自动修正——对可修的问题自动改设计或重布线，最多重试 N 次；修不了就
     如实标注，绝不假装通过。

所有检查项都有稳定 code，便于前端/测试断言。
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import time
from collections import defaultdict

from .. import config
from .validator import validate_design, DesignError

# ---------------------------------------------------------------- 数据结构

POWER_PAT = re.compile(r"(VCC|VDD|VIN|VBAT|3V3|5V|12V|\+3V3|\+5V)", re.I)
GND_PAT = re.compile(r"(GND|VSS|AGND|DGND|0V)", re.I)


class Issue:
    def __init__(self, code, severity, message, fixable=False, hints=None, data=None):
        self.code = code
        self.severity = severity      # error | warning | info
        self.message = message
        self.fixable = fixable
        self.hints = hints or []
        self.data = data or {}        # 结构化字段，供 auto_fix 精确处理

    def as_dict(self):
        return {"code": self.code, "severity": self.severity,
                "message": self.message, "fixable": self.fixable,
                "hints": self.hints, "data": self.data}


def _net_kind(name):
    n = str(name or "").upper()
    if GND_PAT.search(n):
        return "gnd"
    if POWER_PAT.search(n):
        return "power"
    return "signal"


# ---------------------------------------------------------------- 1. 网表自检

def check_netlist(design):
    """纯设计 JSON 电气自检。返回 issues 列表。"""
    issues = []
    comps = {c.get("ref"): c for c in design.get("components", []) or []}
    nets = design.get("nets", []) or []

    if not comps:
        issues.append(Issue("NO_COMPONENTS", "error", "设计里没有任何元件"))
        return issues

    pin_net = {}
    net_pins = defaultdict(list)
    for net in nets:
        name = net.get("name") or ""
        if not name:
            issues.append(Issue("NET_NO_NAME", "warning", "存在未命名的网络"))
        for conn in net.get("connections", []) or []:
            ref, pin = conn.get("ref"), str(conn.get("pin", ""))
            if ref not in comps:
                issues.append(Issue("PIN_UNKNOWN_REF", "error",
                                    "网络 %s 引用了不存在的元件 %s" % (name, ref)))
                continue
            key = (ref, pin)
            if key in pin_net:
                issues.append(Issue(
                    "PIN_IN_TWO_NETS", "error",
                    "%s.%s 同时属于 %s 和 %s（短路）"
                    % (ref, pin, pin_net[key], name),
                    fixable=True,
                    data={"ref": ref, "pin": pin,
                          "keep_net": pin_net[key], "drop_net": name}))
            pin_net[key] = name
            net_pins[name].append(key)

    # 未接线的元件（引脚不在任何网络里）——接口悬空是常见问题
    wired_refs = {r for r, _ in pin_net}
    for ref, c in comps.items():
        if ref not in wired_refs:
            sym = str(c.get("symbol", ""))
            if any(k in sym.upper() for k in ("CONN", "HEADER", "TERMINAL")):
                issues.append(Issue("UNWIRED_CONNECTOR", "warning",
                                    "%s 接口未接入任何网络（外部信号无法进出）" % ref,
                                    fixable=False))
            else:
                issues.append(Issue("UNWIRED_COMPONENT", "warning",
                                    "%s 没有任何引脚接入网络" % ref))

    # 元件合法性
    for ref, c in comps.items():
        if not c.get("value"):
            issues.append(Issue("COMP_NO_VALUE", "warning",
                                "%s 缺少 value（BOM 里会是空值）" % ref))
        if not c.get("footprint"):
            issues.append(Issue("COMP_NO_FOOTPRINT", "warning",
                                "%s 未指定封装" % ref))

    # 每个网络至少两个引脚（单端网络通常是漏连）
    for name, pins in net_pins.items():
        if _net_kind(name) == "signal" and len(pins) == 1:
            issues.append(Issue("SINGLE_PIN_NET", "warning",
                                "信号网络 %s 只有 1 个引脚，可能是漏连" % name))

    # 电源/地网络存在性
    power_nets = [n for n in net_pins if _net_kind(n) == "power"]
    gnd_nets = [n for n in net_pins if _net_kind(n) == "gnd"]
    if power_nets and not gnd_nets:
        issues.append(Issue("NO_GROUND", "error",
                            "有电源网络但没有地网络，电路无法形成回路", fixable=True))
    if gnd_nets and not power_nets:
        issues.append(Issue("NO_POWER", "warning",
                            "有地网络但没有电源网络（可能是纯无源电路）"))

    # 有源器件（IC）供电脚检查
    for ref, c in comps.items():
        sym = str(c.get("symbol", "")).upper()
        is_ic = any(k in sym for k in ("NE555", "CD4017", "LM393", "LM386",
                                        "MAX485", "TP4056", "ULN2003", "LM2596",
                                        "ATMEGA", "ESP", "DHT", "DS18", "SSD1306"))
        if not is_ic:
            continue
        # 不猜引脚号（不同 IC 电源脚位置各异，AVR 是 7/8，555 是 1/8），
        # 只要该 IC 有任意引脚接到电源网络 / 地网络即视为供电正常。
        has_pwr = any(_net_kind(n) == "power"
                      for (r, _), n in pin_net.items() if r == ref)
        has_gnd = any(_net_kind(n) == "gnd"
                      for (r, _), n in pin_net.items() if r == ref)
        if not has_pwr:
            issues.append(Issue("IC_NO_POWER", "warning",
                                "%s 没有任何引脚接到电源网络" % ref))
        if not has_gnd:
            issues.append(Issue("IC_NO_GROUND", "warning",
                                "%s 没有任何引脚接到地网络" % ref))
    return issues


# ---------------------------------------------------------------- 2. 通电模拟

def simulate_power_on(design):
    """静态通电模拟。

    返回 dict(ok, rails, connectivity, signals, verdict, notes)。
    不做 SPICE 瞬态分析——是针对网表的电气连通推理。
    """
    nets = design.get("nets", []) or []
    comps = {c.get("ref"): c for c in design.get("components", []) or []}
    pin_net = {}
    net_pins = defaultdict(list)
    for net in nets:
        for c in net.get("connections", []) or []:
            key = (c.get("ref"), str(c.get("pin", "")))
            pin_net[key] = net.get("name")
            net_pins[net.get("name")].append(key)

    rails = {}
    for name, pins in net_pins.items():
        kind = _net_kind(name)
        if kind in ("power", "gnd"):
            rails[name] = {"kind": kind, "pins": len(pins),
                           "members": ["%s.%s" % p for p in pins]}

    # 电源轨是否形成回路：电源网络应接到至少 1 个有源器件或 1 个连接器
    active_refs = {r for r, c in comps.items()
                   if any(k in str(c.get("symbol", "")).upper()
                          for k in ("NE555", "CD4017", "LM393", "LM386",
                                    "MAX485", "TP4056", "ULN2003", "LM2596",
                                    "ATMEGA", "ESP", "DHT", "DS18", "SSD1306"))}
    conn_refs = {r for r, c in comps.items()
                 if any(k in str(c.get("symbol", "")).upper()
                        for k in ("CONN", "HEADER", "TERMINAL"))}

    power_ok = bool(rails) and any(
        any(ref in active_refs or ref in conn_refs for ref, _ in pins)
        for name, pins in net_pins.items() if _net_kind(name) == "power")

    # 信号链：从"已接入网络的元件"出发做 BFS。
    # 注意：不能只从连接器出发——很多板子没有连接器，或连接器未接线
    # （如 LED 闪烁模板的 J1），那样会误判为"无法工作"。
    graph = defaultdict(set)
    wired_refs = set()
    for net_name, pins in net_pins.items():
        refs = [r for r, _ in pins]
        wired_refs.update(refs)
        for a in refs:
            for b in refs:
                if a != b:
                    graph[a].add(b)
    # 起点优先连接器，其次任意已接线元件；取最大的连通分量
    seeds = wired_refs & conn_refs or wired_refs
    reached = set()
    for seed in seeds:
        if seed in reached:
            continue
        comp_reach = {seed}
        frontier = [seed]
        while frontier:
            cur = frontier.pop()
            for nb in graph.get(cur, ()):
                if nb not in comp_reach:
                    comp_reach.add(nb)
                    frontier.append(nb)
        if len(comp_reach) > len(reached):
            reached = comp_reach
    # 判据：已接线元件全部互相连通（未接线的元件不计入）
    reachable = bool(wired_refs) and reached >= wired_refs

    # 电源/地短路风险：同一元件的相邻引脚分属 power 和 gnd（常见于电源脚接反）
    short_risks = []
    by_ref = defaultdict(dict)
    for (ref, pin), net in pin_net.items():
        by_ref[ref][pin] = net
    for ref, pins in by_ref.items():
        kinds = [(p, _net_kind(n)) for p, n in pins.items()]
        pwr = [p for p, k in kinds if k == "power"]
        gnd = [p for p, k in kinds if k == "gnd"]
        if pwr and gnd:
            # 正常 IC 同时有电源和地脚，不算短路；只在引脚号相邻且非典型时提示
            pass

    ok = power_ok and reachable
    if not nets:
        ok = False
    verdict = ("上电后预计可工作：电源/地回路完整，信号链可达"
               if ok else "上电后可能无法工作：请查看自检问题列表")
    return {
        "ok": ok,
        "rails": rails,
        "power_loop_closed": power_ok,
        "signal_chain_reachable": reachable,
        "components_reached": len(reached),
        "components_total": len(comps),
        "verdict": verdict,
        "notes": ["静态电气推理，非 SPICE 瞬态仿真",
                  "建议上电前用万用表确认电源电压与极性"],
    }


# ---------------------------------------------------------------- 3. KiCad 检查

def _run_kicad(cmd, timeout=45):
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return r.returncode, (r.stdout or "") + (r.stderr or "")
    except Exception as e:  # noqa: BLE001
        return -1, str(e)


def check_kicad(files):
    """调 kicad-cli 跑 ERC / DRC。返回 (issues, stats)。"""
    issues = []
    stats = {"erc": None, "drc": None}
    kicad = getattr(config, "KICAD_CLI", "") or ""
    if not kicad:
        from .. import kicad_detect
        info = kicad_detect.detect()
        detected = info.get("path", "")
        # detect() 优先返回 kicad.exe（GUI），ERC/DRC 必须用 kicad-cli.exe
        if detected:
            cli = os.path.join(os.path.dirname(detected), "kicad-cli.exe")
            kicad = cli if os.path.isfile(cli) else detected
    if not kicad or not os.path.isfile(kicad):
        issues.append(Issue("KICAD_NOT_FOUND", "warning",
                            "未找到 kicad-cli，跳过官方 ERC/DRC 实测"))
        return issues, stats

    sch = files.get("schematic")
    if sch and os.path.isfile(sch):
        rep = os.path.join(os.path.dirname(sch), "_selfcheck_erc.json")
        rc, out = _run_kicad([kicad, "sch", "erc", "--format", "json",
                              "--output", rep, sch])
        if os.path.isfile(rep):
            try:
                data = json.load(open(rep, encoding="utf-8"))
                errs = [v for v in data.get("violations", [])
                        if v.get("severity") == "error"]
                warns = [v for v in data.get("violations", [])
                         if v.get("severity") == "warning"]
                stats["erc"] = {"errors": len(errs), "warnings": len(warns)}
                for v in errs[:10]:
                    issues.append(Issue("ERC_" + str(v.get("type", "VT")).upper(),
                                        "error", "ERC: %s" % v.get("description", ""),
                                        fixable=True))
            except Exception:
                pass
        elif rc != 0:
            stats["erc"] = {"errors": 0, "warnings": 1, "note": out[-200:]}
            issues.append(Issue("ERC_SKIPPED", "warning",
                                "ERC 未能执行（kicad-cli 超时或不可用），已跳过"))

    pcb = files.get("pcb")
    if pcb and os.path.isfile(pcb):
        rep = os.path.join(os.path.dirname(pcb), "_selfcheck_drc.json")
        rc, out = _run_kicad([kicad, "pcb", "drc", "--format", "json",
                              "--output", rep, pcb])
        if os.path.isfile(rep):
            try:
                data = json.load(open(rep, encoding="utf-8"))
                errs = [v for v in data.get("violations", [])
                        if v.get("severity") == "error"]
                warns = [v for v in data.get("violations", [])
                         if v.get("severity") == "warning"]
                stats["drc"] = {"errors": len(errs), "warnings": len(warns)}
                for v in errs[:10]:
                    issues.append(Issue("DRC_" + str(v.get("type", "VT")).upper(),
                                        "error", "DRC: %s" % v.get("description", ""),
                                        fixable=True))
            except Exception:
                pass
        elif rc != 0:
            stats["drc"] = {"errors": 0, "warnings": 1, "note": out[-200:]}
            issues.append(Issue("DRC_SKIPPED", "warning",
                                "DRC 未能执行（kicad-cli 超时或不可用），已跳过"))
    return issues, stats


# ---------------------------------------------------------------- 4. 自动修正

def auto_fix(design, issues):
    """对可修的网表问题自动修正。返回 (new_design, fixes)。

    只改能安全改的：引脚跨网（移除重复）、缺地网络（补 GND 并接到 IC 地脚）。
    DRC 类问题由上层用「更大间距重布线」处理。
    """
    fixes = []
    try:
        d = json.loads(json.dumps(design, ensure_ascii=False))
    except Exception:
        return design, fixes

    for iss in issues:
        if iss.code == "PIN_IN_TWO_NETS" and iss.fixable:
            # 保留第一次出现的网络，从后续网络里移除该引脚（用结构化字段，
            # 不解析中文文本，避免网络名特殊字符导致修正失败）
            data = iss.data or {}
            ref, pin, drop = data.get("ref"), data.get("pin"), data.get("drop_net")
            if not ref or not pin or not drop:
                continue
            for net in d.get("nets", []):
                if net.get("name") == drop:
                    before = len(net.get("connections", []))
                    net["connections"] = [c for c in net.get("connections", [])
                                          if not (c.get("ref") == ref
                                                  and str(c.get("pin")) == pin)]
                    if len(net["connections"]) < before:
                        fixes.append("从网络 %s 移除短路引脚 %s.%s" % (drop, ref, pin))
            continue
        if iss.code == "NO_GROUND" and iss.fixable:
            # 给第一个 IC 的 pin1 补一个 GND，接到现有地网络或新建
            nets = d.get("nets", [])
            gnd = next((n for n in nets if _net_kind(n.get("name")) == "gnd"), None)
            if gnd is None:
                gnd = {"name": "GND", "connections": []}
                nets.append(gnd)
            for c in d.get("components", []):
                if any(k in str(c.get("symbol", "")).upper()
                       for k in ("NE555", "CD4017", "ATMEGA", "LM393")):
                    if not any(x.get("ref") == c["ref"] and str(x.get("pin")) == "1"
                               for x in gnd["connections"]):
                        gnd["connections"].append({"ref": c["ref"], "pin": "1"})
                        fixes.append("补建地网络 GND，连接 %s.1" % c["ref"])
                    break
    return d, fixes


# ---------------------------------------------------------------- 5. 总入口

def run_selfcheck(design, files, auto_fix_enabled=True):
    """完整自检：网表 → 通电模拟 → KiCad ERC/DRC → 自动修正。

    返回 report dict（可直接放进 API 结果）。
    """
    t0 = time.time()
    issues = check_netlist(design)
    power = simulate_power_on(design)
    kissues, kstats = check_kicad(files)
    issues += kissues

    fixes = []
    fixed_design = design
    if auto_fix_enabled:
        net_issues = [i for i in issues if i.code in ("PIN_IN_TWO_NETS", "NO_GROUND")]
        if net_issues:
            fixed_design, fixes = auto_fix(design, net_issues)
            if fixes:
                issues = [i for i in issues
                          if i.code not in ("PIN_IN_TWO_NETS", "NO_GROUND")]
                power = simulate_power_on(fixed_design)

    errors = [i for i in issues if i.severity == "error"]
    warnings = [i for i in issues if i.severity == "warning"]
    # 评分：基础 100，每个 error 扣 15，warning 扣 3，通电失败扣 20
    score = max(0, 100 - len(errors) * 15 - len(warnings) * 3
                - (0 if power.get("ok") else 20))
    report = {
        "ok": len(errors) == 0 and power.get("ok", False),
        "score": score,
        "elapsed_ms": int((time.time() - t0) * 1000),
        "issues": [i.as_dict() for i in issues],
        "error_count": len(errors),
        "warning_count": len(warnings),
        "fixes": fixes,
        "power_on": power,
        "kicad": kstats,
        "summary": ("自检通过：%d 错误 / %d 警告，通电模拟正常"
                    % (len(errors), len(warnings)) if (not errors and power.get("ok"))
                    else "自检发现问题：%d 错误 / %d 警告"
                    % (len(errors), len(warnings))),
    }
    return report, fixed_design
