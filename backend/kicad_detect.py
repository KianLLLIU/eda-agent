# -*- coding: utf-8 -*-
"""
KiCad 安装探测（多策略）
=========================

v2.0.0 的探测只检查 ``C:\\Program Files\\KiCad\\<版本>\\bin`` 和 PATH，
遇到「自定义安装目录」就会误报「未检测到 KiCad」。典型实例：KiCad 10.0.7
装在 ``E:\\BaiduNetdiskDownload``，主程序在 ``<安装目录>\\bin\\kicad.exe``。

现在的探测顺序（命中即返回，同时记录检查过的位置用于诊断）：
  0. 手动指定路径（设置面板 / 环境变量 KICAD_CLI）
  1. Windows 注册表卸载项：DisplayName 含 KiCad → DisplayIcon / InstallLocation
  2. 常见安装根目录 + 各盘符：支持 <root>\\bin 与 <root>\\<版本>\\bin 两种布局
  3. 开始菜单快捷方式（.lnk）里记录的 exe 路径
  4. PATH（kicad / kicad-cli / eeschema / pcbnew）

设计原则：
  · 纯标准库，PyInstaller 打包后可用；
  · 全部只读，不启动 KiCad、不写注册表；
  · 结果带 source / checked / candidates，界面可以直接展示「为什么没找到」。
"""

from __future__ import annotations

import glob
import os
import platform
import re
import shutil
import string
import time

try:
    import winreg
except ImportError:  # pragma: no cover - 非 Windows
    winreg = None

# 打开 .kicad_pro 工程时，优先级从高到低
EXE_NAMES = ("kicad.exe", "eeschema.exe", "pcbnew.exe", "kicad-cli.exe")

_CACHE = {"ts": 0.0, "key": None, "data": None}
_CACHE_TTL = 30.0

_UNINSTALL_KEYS = [
    ("HKLM", r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
    ("HKLM_WOW64", r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"),
    ("HKCU", r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
]

_HIVES = {}
if winreg is not None:
    _HIVES = {
        "HKLM": winreg.HKEY_LOCAL_MACHINE,
        "HKLM_WOW64": winreg.HKEY_LOCAL_MACHINE,
        "HKCU": winreg.HKEY_CURRENT_USER,
    }


def _is_exe(path) -> bool:
    try:
        return bool(path) and os.path.isfile(path) and path.lower().endswith(".exe")
    except Exception:
        return False


def _norm_path(value) -> str:
    if not value:
        return ""
    v = str(value).strip().strip('"').strip("'")
    # DisplayIcon 形如 "E:\...\bin/kicad.exe,0"
    if "," in v and v.lower().endswith((",0", ",1", ",2")):
        v = v.rsplit(",", 1)[0]
    v = v.replace("/", os.sep).replace("\\", os.sep)
    try:
        return os.path.normpath(v)
    except Exception:
        return v


def normalize_manual(value: str) -> str:
    """把用户填的路径规范化成可执行文件：
    填目录 → 追加 bin\\kicad.exe；填 exe → 原样返回；空 → 清空配置。
    """
    v = _norm_path(value)
    if not v:
        return ""
    if v.lower().endswith(".exe"):
        return v
    if os.path.isdir(v):
        for name in EXE_NAMES:
            p = os.path.join(v, "bin", name)
            if _is_exe(p):
                return p
        for name in EXE_NAMES:
            p = os.path.join(v, name)
            if _is_exe(p):
                return p
        return os.path.join(v, "bin", "kicad.exe")
    return v


def _registry_hits(checked: list):
    """返回 [(exe_path, version, source_label), ...]"""
    if winreg is None:
        return []
    found = []
    for label, subpath in _UNINSTALL_KEYS:
        hive = _HIVES.get(label)
        if hive is None:
            continue
        try:
            key = winreg.OpenKey(hive, subpath)
        except Exception:
            checked.append("注册表 %s\\%s（不可读）" % (label, subpath))
            continue
        try:
            count = winreg.QueryInfoKey(key)[0]
            for i in range(count):
                try:
                    sub = winreg.OpenKey(key, winreg.EnumKey(key, i))
                except Exception:
                    continue
                vals = {}
                try:
                    nvals = winreg.QueryInfoKey(sub)[1]
                    for j in range(nvals):
                        name, value, _ = winreg.EnumValue(sub, j)
                        vals[name] = value
                except Exception:
                    pass
                display = str(vals.get("DisplayName", ""))
                if "kicad" not in display.lower() and "kicad" not in str(vals.get("Publisher", "")).lower():
                    continue
                version = str(vals.get("DisplayVersion", "") or "")
                if not version:
                    m = re.search(r"\d+(?:\.\d+)+", display)
                    version = m.group(0) if m else ""
                src = "注册表卸载项 · %s" % (display or label)

                # DisplayIcon 通常直接指向 kicad.exe
                icon = _norm_path(vals.get("DisplayIcon", ""))
                if _is_exe(icon):
                    checked.append("注册表 %s → DisplayIcon: %s" % (display or label, icon))
                    found.append((icon, version, src))
                    continue
                loc = _norm_path(vals.get("InstallLocation", ""))
                checked.append("注册表 %s → InstallLocation: %s" % (display, loc or "(空)"))
                if loc and os.path.isdir(loc):
                    for name in EXE_NAMES:
                        p = os.path.join(loc, "bin", name)
                        if _is_exe(p):
                            found.append((p, version, src))
                            break
                    else:
                        for name in EXE_NAMES:
                            p = os.path.join(loc, name)
                            if _is_exe(p):
                                found.append((p, version, src))
                                break
                # 卸载程序所在目录通常就是安装根目录
                uninst = _norm_path(vals.get("UninstallString", ""))
                m = re.match(r'^("?)([A-Za-z]:\\[^"]+?\.exe)\1', str(vals.get("UninstallString", "")))
                if m:
                    root = os.path.dirname(_norm_path(m.group(2)))
                    p = os.path.join(root, "bin", "kicad.exe")
                    if _is_exe(p):
                        found.append((p, version, src))
        finally:
            try:
                winreg.CloseKey(key)
            except Exception:
                pass
    return found


def _candidate_roots(checked: list):
    roots = []
    env = os.environ
    pf = env.get("ProgramFiles", r"C:\Program Files")
    pf86 = env.get("ProgramFiles(x86)", r"C:\Program Files (x86)")
    roots += [os.path.join(pf, "KiCad"), os.path.join(pf86, "KiCad")]
    la = env.get("LOCALAPPDATA", "")
    if la:
        roots.append(os.path.join(la, "Programs", "KiCad"))
    # 自定义安装目录常见于其它盘符，逐个已存在的盘检查
    if platform.system() == "Windows":
        for letter in string.ascii_uppercase:
            drive = letter + ":\\"
            try:
                if not os.path.isdir(drive):
                    continue
            except Exception:
                continue
            for sub in ("KiCad", os.path.join("Program Files", "KiCad"),
                        os.path.join("Program Files (x86)", "KiCad")):
                roots.append(os.path.join(drive, sub))
    # 去重保序
    seen, out = set(), []
    for r in roots:
        key = os.path.normcase(os.path.normpath(r))
        if key not in seen:
            seen.add(key)
            out.append(r)
    return out


def _directory_hits(checked: list):
    found = []
    for root in _candidate_roots(checked):
        if not os.path.isdir(root):
            continue
        checked.append("目录 %s" % root)
        # 布局 A：<root>\bin\kicad.exe（自定义安装 / 绿色版，本例就是这种）
        for name in EXE_NAMES:
            p = os.path.join(root, "bin", name)
            if _is_exe(p):
                found.append((p, "", "安装目录 · %s" % root))
                break
        else:
            # 布局 B：<root>\<版本>\bin\kicad.exe（官方安装器默认布局）
            try:
                subs = sorted(os.listdir(root), reverse=True)
            except Exception:
                subs = []
            for sub in subs[:12]:
                for name in EXE_NAMES:
                    p = os.path.join(root, sub, "bin", name)
                    if _is_exe(p):
                        found.append((p, sub, "安装目录 · %s" % p))
                        break
                else:
                    continue
                break
    return found


def _lnk_exe_paths(data: bytes):
    """从 .lnk 二进制里提取可能的 exe 绝对路径（ANSI + UTF-16LE 两种编码都试）"""
    out = set()
    for enc in ("latin-1", "utf-16-le"):
        try:
            s = data.decode(enc, errors="ignore")
        except Exception:
            continue
        for m in re.finditer(r"[A-Za-z]:\\[^\x00\r\n<>\"|?*]{2,240}?\.exe", s, re.I):
            p = _norm_path(m.group(0))
            if "kicad" in os.path.basename(p).lower():
                out.add(p)
    return out


def _shortcut_hits(checked: list):
    found = []
    dirs = []
    pd = os.environ.get("ProgramData", "")
    ad = os.environ.get("APPDATA", "")
    if pd:
        dirs.append(os.path.join(pd, "Microsoft", "Windows", "Start Menu", "Programs"))
    if ad:
        dirs.append(os.path.join(ad, "Microsoft", "Windows", "Start Menu", "Programs"))
    for d in dirs:
        if not os.path.isdir(d):
            continue
        for pattern in ("*KiCad*", "**/*KiCad*.lnk"):
            for lnk in glob.glob(os.path.join(d, pattern), recursive=True):
                if not lnk.lower().endswith(".lnk"):
                    continue
                checked.append("快捷方式 %s" % os.path.basename(lnk))
                try:
                    with open(lnk, "rb") as f:
                        paths = _lnk_exe_paths(f.read())
                except Exception:
                    continue
                for p in paths:
                    if _is_exe(p) and "kicad" in os.path.basename(p).lower():
                        found.append((p, "", "开始菜单快捷方式"))
    return found


def _path_hits(checked: list):
    found = []
    for name in ("kicad", "kicad-cli", "eeschema", "pcbnew"):
        p = shutil.which(name)
        if p:
            checked.append("PATH %s → %s" % (name, p))
            found.append((p, "", "系统 PATH"))
    return found


def detect(force: bool = False, manual_path: str = "") -> dict:
    """探测 KiCad，返回结构化结果。

    manual_path 由 config 提供（设置面板 / 环境变量）；force=True 跳过缓存。
    """
    from . import config

    manual = normalize_manual(manual_path or config.RUNTIME.get("kicad_path", "")
                              or config.KICAD_CLI or "")
    key = (manual, config.KICAD_CLI)
    now = time.time()
    if not force and _CACHE["data"] is not None and _CACHE["key"] == key and now - _CACHE["ts"] < _CACHE_TTL:
        return _CACHE["data"]

    checked = []
    candidates = []
    chosen = None

    # 0. 手动指定
    if manual:
        checked.append("手动配置：%s" % manual)
        if _is_exe(manual):
            chosen = (manual, "", "手动指定路径")
            candidates.append(manual)
        else:
            checked.append("手动配置的文件不存在，继续自动探测")

    # 1. 注册表
    if chosen is None:
        for item in _registry_hits(checked):
            if item[0] not in candidates:
                candidates.append(item[0])
            if chosen is None and _is_exe(item[0]):
                chosen = item

    # 2. 常见目录 / 各盘符
    if chosen is None:
        for item in _directory_hits(checked):
            if item[0] not in candidates:
                candidates.append(item[0])
            if chosen is None and _is_exe(item[0]):
                chosen = item

    # 3. 开始菜单快捷方式
    if chosen is None:
        for item in _shortcut_hits(checked):
            if item[0] not in candidates:
                candidates.append(item[0])
            if chosen is None and _is_exe(item[0]):
                chosen = item

    # 4. PATH
    if chosen is None:
        for item in _path_hits(checked):
            if item[0] not in candidates:
                candidates.append(item[0])
            if chosen is None and _is_exe(item[0]):
                chosen = item

    path = chosen[0] if chosen else None
    version = chosen[1] if chosen else ""
    source = chosen[2] if chosen else "未找到"

    if path and not version:
        # 尝试从父目录名（如 9.0 / 10.0）补一个版本号
        parent = os.path.basename(os.path.dirname(os.path.dirname(path)))
        if re.fullmatch(r"\d+(?:\.\d+)+", parent):
            version = parent

    result = {
        "found": bool(path),
        "path": path,
        "version": version,
        "source": source,
        "checked": checked[:30],
        "checked_count": len(checked),
        "candidates": candidates[:12],
        "platform": platform.system(),
        "hint": "" if path else (
            "没有自动找到 KiCad。可以在「设置 → KiCad」里直接填写 kicad.exe 的完整路径，"
            "例如 E:\\BaiduNetdiskDownload\\bin\\kicad.exe；填好后点保存立即生效。"
            "注意：不安装 KiCad 也能生成并下载原理图工程文件。"
        ),
    }
    _CACHE.update({"ts": now, "key": key, "data": result})
    return result


def invalidate():
    """配置变更后清空缓存"""
    _CACHE["data"] = None
    _CACHE["ts"] = 0.0
