# -*- coding: utf-8 -*-
"""Freerouting 自动布线集成（v2.3）

流程：KiCad PCB → Specctra DSN → Freerouting CLI 布线 → SES → 合并回 PCB。

Freerouting v2.5.0 提供 Windows 原生 CLI（GraalVM 编译，免 Java），
放在 tools/freerouting/ 下。也兼容 jar + Java 的情况。

设计原则：
  * 布线是「增强」，失败不能让工程生成失败 —— 任何异常都降级为带飞线的
    原始 PCB，并在结果里说明原因。
  * 超时可控（默认 90s），避免大板卡死。
  * 路径可配置：环境变量 FREEROUTING_BIN / 设置面板 / 自动探测。
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile

from . import config
from .kicad_gen import specctra


_APP_DIR = getattr(config, "APP_DIR",
                   os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_BUNDLE_TOOLS = os.path.join(_APP_DIR, "tools", "freerouting")


def find_java():
    """找 java.exe：优先高版本（jar 需 Java 25+，class 69）。

    PATH 里的 java 版本可能不够，所以收集所有候选后按版本号降序挑。
    """
    import glob as _glob
    import re as _re

    candidates = []
    j = shutil.which("java")
    if j:
        candidates.append(j)
    bundled_java = os.path.join(_APP_DIR, "tools", "java25")
    for root in (bundled_java, r"C:\Program Files\Eclipse Adoptium",
                 r"C:\Program Files\Java", r"C:\Program Files\Eclipse Foundation",
                 r"C:\Program Files (x86)\Java"):
        if os.path.isdir(root):
            candidates += _glob.glob(os.path.join(root, "**", "bin", "java.exe"),
                                     recursive=True)

    def version_key(path):
        m = _re.search(r"jre-?(\d+)|jdk-?(\d+)|[\\/](\d+)[\\/]", path, _re.I)
        if m:
            return int(next(g for g in m.groups() if g) or 0)
        return 0

    candidates = [c for c in candidates if os.path.isfile(c)]
    if candidates:
        return max(candidates, key=version_key)
    return None


def detect():
    """探测 Freerouting 可执行文件。返回 dict(found, path, mode, hint)。"""
    candidates = []
    src_tools = _BUNDLE_TOOLS
    java_exe = find_java()

    # 0. 优先 jar + Java：v2.5 原生 CLI 有 GraalVM 序列化 bug，jar 更稳
    for jar_name in ("freerouting-2.5.0.jar", "freerouting.jar"):
        jar = os.path.join(src_tools, jar_name)
        if (os.path.isfile(jar) and os.path.getsize(jar) > 50_000_000 and java_exe):
            return {"found": True, "path": jar, "mode": "jar", "source": "jar+java",
                    "java": java_exe, "hint": "Freerouting jar + Java（稳定）"}

    # 1. 显式配置
    explicit = os.environ.get("FREEROUTING_BIN", "")
    if explicit:
        candidates.append((explicit, "env"))

    # 2. 运行时设置面板
    try:
        saved = config.RUNTIME.get("freerouting_path", "")
        if saved:
            candidates.append((saved, "settings"))
    except Exception:
        pass

    # 3. 打包内置 tools/freerouting/
    candidates.append((os.path.join(_BUNDLE_TOOLS, "freerouting-cli.exe"), "bundled"))
    candidates.append((os.path.join(_BUNDLE_TOOLS, "freerouting.exe"), "bundled"))

    # 4. 源码目录 tools/freerouting/（解压后的 CLI 名字不定，做模糊查找）
    src_tools = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                             "tools", "freerouting")
    if os.path.isdir(src_tools):
        for name in sorted(os.listdir(src_tools)):
            low = name.lower()
            if ("cli" in low or "freerouting" in low) and low.endswith(".exe"):
                candidates.append((os.path.join(src_tools, name), "local"))

    # 5. PATH 中的 freerouting
    for exe in ("freerouting-cli", "freerouting"):
        p = shutil.which(exe)
        if p:
            candidates.append((p, "path"))

    for path, source in candidates:
        if path and os.path.isfile(path):
            return {"found": True, "path": path, "mode": "cli", "source": source,
                    "hint": "Freerouting CLI 已就绪"}

    # 6. jar + Java（v2.5 原生 CLI 有 GraalVM 序列化 bug，优先用 jar）
    for jar_name in ("freerouting-2.5.0.jar", "freerouting.jar"):
        jar = os.path.join(src_tools, jar_name)
        if os.path.isfile(jar) and os.path.getsize(jar) > 50_000_000 and shutil.which("java"):
            return {"found": True, "path": jar, "mode": "jar", "source": "jar+java",
                    "hint": "Freerouting jar + Java（稳定）"}

    return {
        "found": False, "path": "", "mode": "", "source": "",
        "hint": ("未找到 Freerouting。请把 freerouting-2.5.0.jar 或 "
                 "freerouting-cli.exe 放到 tools/freerouting/，或在设置面板指定。"),
    }


def _build_cmd(exe_info, dsn_path, ses_path, ignore_nets=("GND", "VCC")):
    if exe_info["mode"] == "jar":
        java = exe_info.get("java") or find_java() or "java"
        cmd = [java, "-jar", exe_info["path"]]
    else:
        cmd = [exe_info["path"]]
    # 原生 CLI 支持 -de/-do/-mp/-l；-l zh 让日志/提示用中文
    cmd += ["-de", dsn_path, "-do", ses_path, "-mp", "8", "-l", "zh"]
    return cmd


def route_board(design, pcb_text, work_dir, timeout=90, ignore_nets=("GND", "VCC")):
    """对一块 PCB 自动布线。

    返回 dict(ok, pcb_text, stats, error)。失败时 ok=False，pcb_text 原样返回。
    """
    exe = detect()
    if not exe["found"]:
        return {"ok": False, "pcb_text": pcb_text,
                "stats": {}, "error": exe["hint"]}

    # Freerouting 原生 CLI（GraalVM）在 Windows 上读不了中文路径，
    # 必须在纯 ASCII 的临时目录里跑，布完再把 SES 读回来。
    ascii_dir = os.path.join(tempfile.gettempdir(), "eda_fr_route")
    try:
        os.makedirs(ascii_dir, exist_ok=True)
    except Exception:
        ascii_dir = work_dir
    dsn_path = os.path.join(ascii_dir, "board.dsn")
    ses_path = os.path.join(ascii_dir, "board.ses")

    # 1. 导出 DSN
    try:
        dsn, dsn_stats = specctra.export_dsn(design, pcb_text)
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "pcb_text": pcb_text, "stats": {},
                "error": "DSN 导出失败: %s" % e}
    with open(dsn_path, "w", encoding="utf-8") as f:
        f.write(dsn)

    # 2. 调用 Freerouting CLI（原生 CLI 只认 -de/-do/-mp/-l）
    cmd = _build_cmd(exe, dsn_path, ses_path, ignore_nets)
    try:
        # stdout/stderr 重定向到文件，避免管道缓冲导致 timeout 失效
        log_path = os.path.join(ascii_dir, "freerouting.log")
        with open(log_path, "w", encoding="utf-8", errors="replace") as log:
            proc = subprocess.Popen(
                cmd, stdout=log, stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL, cwd=work_dir,
                creationflags=(subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0),
            )
            try:
                rc = proc.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                # 杀整棵进程树
                if sys.platform == "win32":
                    subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                                   capture_output=True)
                else:
                    proc.kill()
                return {"ok": False, "pcb_text": pcb_text, "stats": dsn_stats,
                        "error": "Freerouting 超时（%ss）" % timeout}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "pcb_text": pcb_text, "stats": dsn_stats,
                "error": "启动 Freerouting 失败: %s" % e}

    if not os.path.isfile(ses_path):
        tail = ""
        try:
            tail = open(log_path, encoding="utf-8", errors="replace").read()[-400:]
        except Exception:
            pass
        return {"ok": False, "pcb_text": pcb_text, "stats": dsn_stats,
                "error": "Freerouting 未生成 SES（rc=%s）: %s" % (rc, tail)}

    # 3. SES 合并回 PCB
    try:
        ses = open(ses_path, encoding="utf-8", errors="replace").read()
        new_pcb, merge_stats = specctra.merge_ses(pcb_text, ses, design)
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "pcb_text": pcb_text, "stats": dsn_stats,
                "error": "SES 导入失败: %s" % e}

    stats = {**dsn_stats, **merge_stats, "engine": "freerouting-v2.5"}
    if merge_stats.get("segments", 0) == 0:
        return {"ok": False, "pcb_text": pcb_text, "stats": stats,
                "error": "Freerouting 没有布出任何走线"}
    return {"ok": True, "pcb_text": new_pcb, "stats": stats, "error": ""}
