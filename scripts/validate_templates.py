# -*- coding: utf-8 -*-
"""模板库批量验收脚本

对 backend/templates 下每个模板执行：
  1. 调用 pipeline 生成完整 KiCad 工程（原理图 / PCB / BOM / 网表）
  2. kicad-cli 导出原理图 SVG（验证语法与图形）
  3. kicad-cli sch erc  （电气规则检查）
  4. kicad-cli pcb drc  （设计规则检查）
  5. kicad-cli pcb export svg（验证 PCB 图形可导出）
  6. 统计 wire / junction / pad / footprint 数量，检查是否「空壳」

用法：
    python scripts/validate_templates.py            # 全部模板
    python scripts/validate_templates.py led_blink  # 指定模板
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from backend.agent import pipeline  # noqa: E402
from backend import kicad_detect  # noqa: E402


def kicad_cli():
    info = kicad_detect.detect()
    path = info.get("path") or ""
    if not path:
        return None
    exe = os.path.join(os.path.dirname(path), "kicad-cli.exe")
    return exe if os.path.isfile(exe) else None


def run(cli, args, timeout=240):
    try:
        p = subprocess.run([cli] + args, capture_output=True, timeout=timeout,
                           stdin=subprocess.DEVNULL)
        return p.returncode, (p.stdout or b"").decode("utf-8", "replace") + \
                             (p.stderr or b"").decode("utf-8", "replace")
    except subprocess.TimeoutExpired:
        return -9, "timeout"


def severity_counts(report_path):
    if not os.path.isfile(report_path):
        return {}
    try:
        with open(report_path, encoding="utf-8") as f:
            data = json.load(f)
    except Exception:  # noqa: BLE001
        return {}
    out = {}
    for v in data.get("violations", []) or []:
        sev = (v.get("severity") or "unknown").lower()
        out[sev] = out.get(sev, 0) + 1
    return out


def count(path, pattern):
    if not os.path.isfile(path):
        return 0
    with open(path, encoding="utf-8", errors="replace") as f:
        return len(re.findall(pattern, f.read()))


def check(name, cli, workroot):
    design = pipeline.load_template_by_name(name)
    outdir = os.path.join(workroot, name)
    os.makedirs(outdir, exist_ok=True)
    files = pipeline.build_project_files(design, outdir, "proj")

    res = {"name": name, "comps": len(design.get("components", [])),
           "nets": len(design.get("nets", [])),
           "wires": count(files["schematic"], r"\(wire\b"),
           "junctions": count(files["schematic"], r"\(junction\b"),
           "pads": count(files["pcb"], r"\(pad\b"),
           "footprints": count(files["pcb"], r"\n\s*\(footprint\b"),
           "sch_bytes": os.path.getsize(files["schematic"]),
           "pcb_bytes": os.path.getsize(files["pcb"])}

    if not cli:
        res["note"] = "未找到 kicad-cli"
        return res

    svg_dir = os.path.join(outdir, "svg")
    os.makedirs(svg_dir, exist_ok=True)
    code, log = run(cli, ["sch", "export", "svg", "-o", svg_dir, files["schematic"]])
    res["sch_svg"] = code
    erc_json = os.path.join(outdir, "erc.json")
    code, log = run(cli, ["sch", "erc", "--format", "json", "-o", erc_json, files["schematic"]])
    res["erc"] = severity_counts(erc_json)
    res["erc_err"] = res["erc"].get("error", 0)
    drc_json = os.path.join(outdir, "drc.json")
    code, log = run(cli, ["pcb", "drc", "--format", "json", "-o", drc_json, files["pcb"]])
    res["drc"] = severity_counts(drc_json)
    res["drc_err"] = res["drc"].get("error", 0)
    code, log = run(cli, ["pcb", "export", "svg", "-o", os.path.join(svg_dir, "pcb.svg"),
                          "--layers", "F.Cu,B.Cu,F.SilkS,Edge.Cuts", files["pcb"]])
    res["pcb_svg"] = code
    return res


def main():
    names = sys.argv[1:] or list(pipeline.TEMPLATES.keys())
    cli = kicad_cli()
    print("kicad-cli:", cli or "<missing>")
    workroot = tempfile.mkdtemp(prefix="eda_tpl_")
    rows, bad = [], []
    for n in names:
        try:
            r = check(n, cli, workroot)
        except Exception as e:  # noqa: BLE001
            print("[FAIL] %-20s %s: %s" % (n, type(e).__name__, e))
            bad.append(n)
            continue
        rows.append(r)
        flag = "OK  "
        if r.get("sch_svg", 0) or r.get("pcb_svg", 0):
            flag = "FAIL"
        if r.get("erc_err") or r.get("drc_err"):
            flag = "WARN" if not (r.get("erc_err")) else "ERC!"
        if r["pads"] < 2 or r["footprints"] < 1:
            flag = "FAIL"
        print("[%s] %-20s 元件%2d 网络%2d wire%3d junc%3d 焊盘%3d 封装%2d ERC%2d/%2d DRC%2d/%2d"
              % (flag, r["name"], r["comps"], r["nets"], r["wires"], r["junctions"],
                 r["pads"], r["footprints"],
                 r["erc_err"], sum(r.get("erc", {}).values()),
                 r["drc_err"], sum(r.get("drc", {}).values())))
        if flag in ("FAIL", "ERC!"):
            bad.append(n)
    print("\n输出目录:", workroot)
    print("总计 %d 个模板，问题 %d 个" % (len(rows), len(bad)))
    if bad:
        print("需要修复:", ", ".join(bad))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
