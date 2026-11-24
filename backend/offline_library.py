# -*- coding: utf-8 -*-
"""
离线板子库（Offline Board Library）
===================================

把两类板子统一成一个可管理的库：
  1. builtin —— 项目自带的 23 块模板（只读，source=builtin）
  2. user    —— 对话生成后自动归档 / 用户手动新增的板子（可增删改，source=user）

每次绘图完成会把「任务特征」（功能/器件/接口/参数标签）连同 design.json 一起归档，
后续用户再描述相似需求时，可按特征检索直接调用，不必重新生成。

存储结构（落在 config.USER_DATA_DIR/offline_library/，跨会话、卸载可清理）：
    index.json            # {"items": {id: meta}}
    designs/<id>.json     # 用户板子的完整 design JSON
内置模板不复制文件，meta 里记 template_id，读取时从 config.TEMPLATE_DIR 加载。

纯标准库实现，线程安全用简单锁兜底；任何单条失败都不影响整体流程。
"""

from __future__ import annotations

import json
import os
import threading
import time
import uuid

from . import config
from .agent import nlu
from .agent.pipeline import TEMPLATES, TEMPLATE_CATEGORIES

LIB_DIR = os.path.join(config.USER_DATA_DIR, "offline_library")
INDEX_FILE = os.path.join(LIB_DIR, "index.json")
DESIGNS_DIR = os.path.join(LIB_DIR, "designs")

_LOCK = threading.RLock()

# 内置模板分类 → 特征标签（用于相似检索；与 nlu.TEMPLATE_SIGNALS 互补）
_BUILTIN_TAGS = {
    "电源": ["稳压", "供电", "电源"], "LED 灯光": ["指示灯", "闪烁", "LED"],
    "传感器": ["采集", "检测", "传感器"], "驱动": ["驱动", "继电器", "电机"],
    "接口": ["通信", "接口", "模块"],
}


def _ensure_dirs():
    os.makedirs(DESIGNS_DIR, exist_ok=True)


# ---------------------------------------------------------------------------
# 索引读写
# ---------------------------------------------------------------------------
def _load_index() -> dict:
    try:
        if os.path.isfile(INDEX_FILE):
            with open(INDEX_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception:
        pass
    return {"items": {}}


def _save_index(idx: dict):
    try:
        _ensure_dirs()
        tmp = INDEX_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(idx, f, ensure_ascii=False, indent=1)
        os.replace(tmp, INDEX_FILE)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# 特征抽取
# ---------------------------------------------------------------------------
def extract_features(design: dict, requirement: str = "", analysis: dict | None = None) -> dict:
    """从一次任务里抽取可复用的特征标签"""
    analysis = analysis or {}
    func, comp, intf, params = [], [], [], []
    for k in analysis.get("keywords", []) or []:
        cat, term = k.get("category"), k.get("term")
        if cat == "功能":
            func.append(term)
        elif cat == "元件":
            comp.append(term)
        elif cat == "接口":
            intf.append(term)
        elif cat == "参数":
            params.append(term)
    # 补充：从 design 的元件值里提炼关键器件型号（大写字母+数字，如 NE555/AMS1117/DHT11）
    refs = []
    for c in (design or {}).get("components", []) or []:
        for val in (str(c.get("value", "")), str(c.get("symbol", ""))):
            for m in __import__("re").finditer(r"\b([A-Z]{2,}[A-Z0-9\-]{1,10})\b", val):
                tag = m.group(1)
                if tag not in refs and tag not in ("VCC", "GND", "R", "C", "LED"):
                    refs.append(tag)
    comp = list(dict.fromkeys(comp + refs))[:10]
    cat = _guess_category(func + comp + intf)
    return {
        "function": list(dict.fromkeys(func))[:8],
        "component": list(dict.fromkeys(comp))[:10],
        "interface": list(dict.fromkeys(intf))[:6],
        "param": list(dict.fromkeys(params))[:6],
        "category": cat,
        "text": str(requirement or "")[:120],
    }


def _guess_category(terms: list[str]) -> str:
    joined = " ".join(terms).lower()
    if any(x in joined for x in ("稳压", "降压", "充电", "电源", "ldo", "buck")):
        return "电源"
    if any(x in joined for x in ("led", "闪烁", "呼吸", "流水", "指示灯", "灯带")):
        return "LED 灯光"
    if any(x in joined for x in ("温度", "湿度", "光敏", "气体", "测距", "传感器", "采集")):
        return "传感器"
    if any(x in joined for x in ("驱动", "继电器", "电机", "蜂鸣", "功放")):
        return "驱动"
    if any(x in joined for x in ("i2c", "spi", "uart", "485", "wifi", "usb", "接口", "通信")):
        return "接口"
    return "其他"


# ---------------------------------------------------------------------------
# 内置模板（统一视图，只读）
# ---------------------------------------------------------------------------
def _builtin_items() -> list[dict]:
    out = []
    for tid, meta in TEMPLATES.items():
        out.append({
            "id": "builtin:" + tid,
            "source": "builtin",
            "template_id": tid,
            "name": meta["name"],
            "title": meta["name"],
            "description": meta["desc"],
            "category": meta["category"],
            "tags": _BUILTIN_TAGS.get(meta["category"], []) + [s[0] for s in nlu.TEMPLATE_SIGNALS.get(tid, [])[:5]],
            "features": {"category": meta["category"], "text": meta["desc"]},
            "use_count": 0,
            "created_at": 0,
            "updated_at": 0,
        })
    return out


def _builtin_design(template_id: str) -> dict:
    path = os.path.join(config.TEMPLATE_DIR, TEMPLATES[template_id]["file"])
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# 公共 API
# ---------------------------------------------------------------------------
def list_items(category: str | None = None, source: str | None = None) -> list[dict]:
    """统一列表：内置 + 用户归档，用户条目按更新时间降序在前"""
    with _LOCK:
        idx = _load_index()
        items = _builtin_items()
        for iid, meta in idx.get("items", {}).items():
            m = dict(meta)
            m["id"] = iid
            m["source"] = "user"
            # 统计实际元件/网络数
            try:
                d = _read_design(iid)
                m["component_count"] = len(d.get("components", []))
                m["net_count"] = len(d.get("nets", []))
            except Exception:
                m["component_count"] = m.get("component_count", 0)
                m["net_count"] = m.get("net_count", 0)
            items.append(m)
    users = sorted([x for x in items if x["source"] == "user"],
                   key=lambda x: -x.get("updated_at", 0))
    builtins = [x for x in items if x["source"] == "builtin"]
    result = users + builtins
    if category:
        result = [x for x in result if x.get("category") == category]
    if source:
        result = [x for x in result if x["source"] == source]
    return result


def categories() -> list[dict]:
    items = list_items()
    counts: dict[str, int] = {}
    for x in items:
        c = x.get("category", "其他")
        counts[c] = counts.get(c, 0) + 1
    ordered = [c for c in TEMPLATE_CATEGORIES if c in counts]
    ordered += [c for c in counts if c not in ordered]
    return [{"name": c, "count": counts[c]} for c in ordered]


def get_item(item_id: str) -> dict:
    """返回 {"meta": ..., "design": ...}，内置/用户都支持"""
    if item_id.startswith("builtin:"):
        tid = item_id.split(":", 1)[1]
        if tid not in TEMPLATES:
            raise KeyError("未知内置模板: " + tid)
        meta = next((x for x in _builtin_items() if x["id"] == item_id), {})
        return {"meta": meta, "design": _builtin_design(tid)}
    with _LOCK:
        idx = _load_index()
        meta = idx.get("items", {}).get(item_id)
        if not meta:
            raise KeyError("库中无此板子: " + item_id)
        meta = dict(meta)
        meta["id"] = item_id
        meta["source"] = "user"
        return {"meta": meta, "design": _read_design(item_id)}


def _design_path(item_id: str) -> str:
    return os.path.join(DESIGNS_DIR, item_id + ".json")


def _read_design(item_id: str) -> dict:
    with open(_design_path(item_id), "r", encoding="utf-8") as f:
        return json.load(f)


def archive(design: dict, requirement: str = "", analysis: dict | None = None,
            name: str = "", description: str = "", tags: list[str] | None = None,
            dedupe: bool = True, project_name: str = "") -> dict:
    """把一次任务归档为可复用条目。相似需求重复出现时只累加 use_count，不新建。"""
    features = extract_features(design, requirement, analysis)
    now = time.time()
    norm_req = " ".join(str(requirement or "").lower().split())[:80]
    with _LOCK:
        _ensure_dirs()
        idx = _load_index()
        items = idx.setdefault("items", {})
        # 去重：同名或同需求描述已归档 → 只更新计数与时间
        if dedupe:
            for iid, meta in items.items():
                if norm_req and meta.get("requirement_norm") == norm_req:
                    meta["use_count"] = meta.get("use_count", 1) + 1
                    meta["updated_at"] = now
                    _save_index(idx)
                    meta = dict(meta)
                    meta["id"] = iid
                    meta["source"] = "user"
                    meta["deduped"] = True
                    return meta
        iid = "user-" + uuid.uuid4().hex[:10]
        with open(_design_path(iid), "w", encoding="utf-8") as f:
            json.dump(design, f, ensure_ascii=False, indent=2)
        meta = {
            "name": name or design.get("title") or norm_req[:20] or "未命名板子",
            "title": design.get("title", ""),
            "description": description or norm_req or features["text"],
            "category": features["category"],
            "tags": list(tags or []) + features["function"][:3] + features["component"][:3],
            "features": features,
            "requirement_norm": norm_req,
            "component_count": len(design.get("components", [])),
            "net_count": len(design.get("nets", [])),
            "use_count": 1,
            "created_at": now,
            "updated_at": now,
            "project_name": project_name,
        }
        items[iid] = meta
        _save_index(idx)
        meta = dict(meta)
        meta["id"] = iid
        meta["source"] = "user"
        return meta


def add_item(name: str, description: str, category: str, design: dict,
             tags: list[str] | None = None) -> dict:
    """用户手动新增一块板子（带完整 design JSON）"""
    from .agent.validator import validate_design
    design = validate_design(design)
    features = extract_features(design, description)
    return archive(design, description, None, name=name, description=description,
                   tags=(tags or []) + [category] if category not in (tags or []) else tags,
                   dedupe=False)


def update_item(item_id: str, patch: dict) -> dict:
    """修改描述 / 名称 / 分类 / 标签（内置模板不可改）"""
    if item_id.startswith("builtin:"):
        raise PermissionError("内置模板只读，不能修改")
    with _LOCK:
        idx = _load_index()
        meta = idx.get("items", {}).get(item_id)
        if not meta:
            raise KeyError("库中无此板子: " + item_id)
        for key in ("name", "description", "category", "tags", "features"):
            if key in patch and patch[key] is not None:
                meta[key] = patch[key]
        meta["updated_at"] = time.time()
        _save_index(idx)
        out = dict(meta)
        out["id"] = item_id
        out["source"] = "user"
        return out


def delete_item(item_id: str) -> bool:
    """删除用户条目（内置模板不可删）"""
    if item_id.startswith("builtin:"):
        raise PermissionError("内置模板只读，不能删除")
    with _LOCK:
        idx = _load_index()
        if item_id not in idx.get("items", {}):
            return False
        del idx["items"][item_id]
        _save_index(idx)
        path = _design_path(item_id)
        if os.path.isfile(path):
            try:
                os.remove(path)
            except Exception:
                pass
        return True


def search(text: str, top_k: int = 5) -> list[dict]:
    """按特征相似度为一句需求匹配库里的板子（内置 + 用户统一检索）"""
    analysis = nlu.analyze(text)
    want = set()
    for k in analysis.get("keywords", []):
        want.add(k.get("term"))
    for v in (analysis.get("entities", {}).get("voltage", []) or []):
        want.add(v)
    want |= {w for w in _tokens(text)}
    ranked = []
    for item in list_items():
        score = 0
        tags = set()
        for group in ("function", "component", "interface", "param"):
            tags |= set((item.get("features", {}) or {}).get(group, []) or [])
        tags |= set(item.get("tags", []) or [])
        tags |= set(_tokens(item.get("description", "")))
        tags |= set(_tokens(item.get("name", "")))
        for tag in tags:
            if tag and tag in want:
                score += 3
            elif tag and any(tag in w or w in tag for w in want if len(tag) >= 3 and len(w) >= 3):
                score += 1
        # 内置模板用官方信号再补一轮加权
        if item["source"] == "builtin":
            for term, weight in nlu.TEMPLATE_SIGNALS.get(item.get("template_id", ""), []):
                if term.lower() in str(text).lower():
                    score += weight
        if score > 0:
            ranked.append({**item, "match_score": score})
    ranked.sort(key=lambda x: -x["match_score"])
    return ranked[:top_k]


def _tokens(text: str) -> set[str]:
    """中英文混排粗分词：英文/数字整词 + 中文 2-gram"""
    s = str(text or "").lower()
    out = set(__import__("re").findall(r"[a-z0-9][a-z0-9\-]{1,}", s))
    cn = "".join(__import__("re").findall(r"[\u4e00-\u9fff]", s))
    for i in range(len(cn) - 1):
        out.add(cn[i:i + 2])
    return out


def stats() -> dict:
    items = list_items()
    return {
        "total": len(items),
        "builtin": sum(1 for x in items if x["source"] == "builtin"),
        "user": sum(1 for x in items if x["source"] == "user"),
        "categories": categories(),
        "storage": LIB_DIR,
    }


def mark_used(item_id: str):
    """套用一次后累加使用计数"""
    if item_id.startswith("builtin:"):
        return
    with _LOCK:
        idx = _load_index()
        meta = idx.get("items", {}).get(item_id)
        if meta:
            meta["use_count"] = meta.get("use_count", 0) + 1
            meta["updated_at"] = time.time()
            _save_index(idx)
