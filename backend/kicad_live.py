# -*- coding: utf-8 -*-
"""KiCad 实时联动（v2.3）

「边生成边在 KiCad 里更新」——通过官方 KiCad IPC API（kicad-python /
kipy）连接正在运行的 KiCad 10，把 agent 摆放好的元件实时推到 PCB 编辑器。

kipy 依赖装在 tools/pylibs/kipy（独立目录），通过子进程脚本调用，
不污染主程序运行时。IPC server 需要在 KiCad 里开启：
  Preferences → Plugins → Enable IPC API Server

三级策略：
  1. IPC 已开启 → 实时推送元件/走线到打开的 PCB（真·实时绘图）
  2. IPC 未开启 → 引导用户开启，同时自动用 KiCad 打开生成的工程
  3. 都不是 → 返回文件模式，用户在网页 SVG 看预览

所有操作都容错：IPC 失败不影响文件生成，只是没有实时联动。
"""

from __future__ import annotations

import json
import os
import subprocess
import sys

from . import config, kicad_detect

_APP_DIR = getattr(config, "APP_DIR",
                   os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
KIPY_DIR = os.path.join(_APP_DIR, "tools", "pylibs", "kipy")
BRIDGE_SCRIPT = os.path.join(_APP_DIR, "scripts", "kicad_ipc_bridge.py")


def _kicad_config_path():
    return os.path.join(os.path.expanduser("~"), "AppData", "Roaming",
                        "kicad", "10.0", "kicad_common.json")


def ipc_status():
    """探测 KiCad IPC server 是否可以连接。返回结构化状态。"""
    cfg = _kicad_config_path()
    enabled = False
    if os.path.isfile(cfg):
        try:
            data = json.load(open(cfg, encoding="utf-8"))
            enabled = bool(data.get("api", {}).get("enable_server", False))
        except Exception:
            pass
    kicad = kicad_detect.detect()
    return {
        "ipc_enabled": enabled,
        "config_path": cfg,
        "kicad_found": kicad.get("found", False),
        "kicad_version": kicad.get("version", ""),
        "bridge_ready": os.path.isfile(BRIDGE_SCRIPT) and os.path.isdir(KIPY_DIR),
        "hint": ("IPC 已开启，可实时联动" if enabled else
                 "请在 KiCad: Preferences → Plugins → Enable IPC API Server 开启后重启 KiCad"),
    }


def enable_ipc():
    """写入配置开启 KiCad IPC server（需重启 KiCad 生效）。"""
    cfg = _kicad_config_path()
    if not os.path.isfile(cfg):
        return {"ok": False, "error": "未找到 KiCad 配置文件，请先启动一次 KiCad"}
    try:
        data = json.load(open(cfg, encoding="utf-8"))
        data.setdefault("api", {})["enable_server"] = True
        with open(cfg, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        return {"ok": True, "message": "已开启 IPC API Server，请重启 KiCad 生效"}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": str(e)}


def open_in_kicad(pcb_path):
    """用 KiCad PCB 编辑器打开指定板子（不依赖 IPC，最稳）。"""
    kicad = kicad_detect.detect()
    if not kicad.get("found"):
        return {"ok": False, "error": "未检测到 KiCad 安装"}
    exe = kicad.get("path", "")
    # detect() 返回的是 kicad-cli 或 kicad.exe，取目录拼 pcbnew.exe
    bindir = os.path.dirname(exe)
    pcbnew = os.path.join(bindir, "pcbnew.exe")
    if not os.path.isfile(pcbnew):
        pcbnew = exe
    try:
        subprocess.Popen([pcbnew, pcb_path],
                         creationflags=(subprocess.CREATE_NO_WINDOW
                                        if sys.platform == "win32" else 0))
        return {"ok": True, "exe": pcbnew, "pcb": pcb_path}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": str(e)}


def push_preview(design, pcb_path):
    """通过 IPC bridge 把元件实时推到已打开的 KiCad PCB。

    返回 dict(ok, message)。IPC 不可用时优雅失败。
    """
    status = ipc_status()
    if not status["ipc_enabled"]:
        return {"ok": False, "error": "IPC 未开启", "hint": status["hint"]}
    if not status["bridge_ready"]:
        return {"ok": False, "error": "kipy 桥接未就绪"}

    payload = json.dumps({"design": design, "pcb_path": pcb_path}, ensure_ascii=False)
    try:
        proc = subprocess.run(
            [sys.executable, BRIDGE_SCRIPT, payload],
            capture_output=True, text=True, timeout=30,
            env={**os.environ, "PYTHONPATH": KIPY_DIR},
        )
        if proc.returncode == 0:
            return {"ok": True, "message": (proc.stdout or "").strip()[:200]}
        return {"ok": False, "error": (proc.stderr or proc.stdout or "").strip()[-300:]}
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "IPC 桥接超时"}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": str(e)}
