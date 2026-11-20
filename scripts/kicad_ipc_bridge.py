# -*- coding: utf-8 -*-
"""KiCad IPC 桥接（子进程，由 backend/kicad_live.py 调用）

连接正在运行的 KiCad 10 IPC server，做实时联动：
  * ping / 版本检查
  * 列出打开的文档
  * 获取当前 PCB 的封装 / 网络 / 走线统计
  * 可选：把新元件通过 create_items 推到打开的 PCB（实时绘图）

用法：
  python kicad_ipc_bridge.py '<json payload>'
  payload = {"action": "status"|"push"|"save", "design": {...}, "pcb_path": "..."}

依赖 kipy 装在 tools/pylibs/kipy（由调用方设置 PYTHONPATH）。
"""

from __future__ import annotations

import json
import os
import sys

# kipy 由 PYTHONPATH 注入；这里兜底再插一次
_HERE = os.path.dirname(os.path.abspath(__file__))
_KIPY = os.path.join(os.path.dirname(_HERE), "tools", "pylibs", "kipy")
if os.path.isdir(_KIPY) and _KIPY not in sys.path:
    sys.path.insert(0, _KIPY)


def _connect():
    from kipy import KiCad
    k = KiCad(client_name="eda-agent")
    return k


def action_status(k):
    result = {
        "connected": True,
        "version": str(k.get_version()),
        "api_version": str(k.get_api_version()),
    }
    # 打开着 PCB 就报统计（kipy 连上后 get_board 才有意义）
    try:
        board = k.get_board()
        fps = board.get_footprints()
        nets = board.get_nets()
        tracks = board.get_tracks()
        result["board"] = {
            "footprints": len(fps),
            "nets": len(nets),
            "tracks": len(tracks),
        }
    except Exception as e:
        result["board"] = {"open": False, "note": str(e)[:120]}
    return result


def action_push(k, design):
    """把 design 里的元件位置推到当前打开的 PCB。

    kipy 构造完整封装需要库加载，复杂且依赖板子已关联库。这里做
    「位置同步」：对当前板上已存在的封装，按 design.positions 更新坐标。
    若板子为空，则报告需要先用文件方式打开生成的板子。
    """
    board = k.get_board()
    fps = board.get_footprints()
    by_ref = {}
    for fp in fps:
        try:
            by_ref[str(fp.reference)] = fp
        except Exception:
            pass

    target = {}
    for c in design.get("components", []) or []:
        ref = c.get("ref")
        pos = c.get("position") or {}
        if ref and isinstance(pos, dict) and "x" in pos and "y" in pos:
            target[ref] = (float(pos["x"]), float(pos["y"]))

    updated = 0
    to_update = []
    for ref, fp in by_ref.items():
        if ref not in target:
            continue
        x, y = target[ref]
        try:
            fp.position = x, y          # kipy Vector2 可通过 setattr 更新
            to_update.append(fp)
            updated += 1
        except Exception:
            pass
    if to_update:
        commit = board.begin_commit()
        board.update_items(to_update)
        board.push_commit(commit)
    return {"pushed": updated, "on_board": len(by_ref), "targets": len(target)}


def action_save(k):
    board = k.get_board()
    board.save()
    return {"saved": True}


def main():
    if len(sys.argv) < 2:
        print(json.dumps({"ok": False, "error": "缺少 payload"}))
        return
    try:
        payload = json.loads(sys.argv[1])
    except Exception as e:
        print(json.dumps({"ok": False, "error": "payload 解析失败: %s" % e}))
        return
    action = payload.get("action", "status")
    try:
        k = _connect()
        if action == "status":
            data = action_status(k)
        elif action == "push":
            data = action_push(k, payload.get("design") or {})
        elif action == "save":
            data = action_save(k)
        else:
            data = {"error": "未知 action: %s" % action}
        print(json.dumps({"ok": True, "action": action, "data": data}, ensure_ascii=False))
    except Exception as e:  # noqa: BLE001
        import traceback
        print(json.dumps({"ok": False, "error": str(e),
                          "trace": traceback.format_exc()[-500:]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
