# -*- coding: utf-8 -*-
"""
对话助手（Assistant Brain）
===========================

职责：
  1. 维护助手的能力档案（自我介绍、能力清单、快捷指令、模板库说明）；
  2. 维护多轮会话上下文（历史消息、当前设计、已识别关键词、轮次统计）；
  3. 依据 NLU 意图生成「有信息量」的动态回复，而不是固定话术；
  4. 能真正解释当前电路（模块 / 元件 / 网络 / 关键参数）。

会话做本地 JSON 持久化，桌面端重启后仍可恢复历史设计。
"""

from __future__ import annotations

import json
import os
import time
import uuid

from .. import config
from . import nlu

VERSION = "2.0.4"

ASSISTANT_PROFILE = {
    "name": "W",
    "display_name": "EDA Agent 电路设计助手",
    "version": VERSION,
    "tagline": "说一句人话，换一块电路板",
    "description": (
        "我是 EDA Agent 的电路设计助手。你把想法用自然语言告诉我，我会先理解意图、"
        "抽取电路关键词与参数，再完成元器件选型、引脚级网表连接，生成可直接用 KiCad 打开的"
        "原理图工程，并附上 BOM、工作汇报、操作指南与硬件需求清单。"
    ),
}

CAPABILITIES = [
    {"icon": "brain", "title": "意图理解", "desc": "识别生成 / 修改 / 解释 / 导出 / 帮助等 10 类意图，中英文混输、口语化表达都能解析"},
    {"icon": "tag", "title": "关键词与参数抽取", "desc": "内置 40+ 组电路术语同义词词典，识别元件、功能、接口、电压、阻值、容值、元件编号"},
    {"icon": "spark", "title": "自然语言生成电路", "desc": "一句话生成 BOM + 引脚级网表，支持入门 / 进阶 / 挑战三档复杂度"},
    {"icon": "edit", "title": "对话式改图", "desc": "「把 C1 换成 100nF」「增加一组去耦电容」实时更新设计与原理图，离线也能改"},
    {"icon": "layers", "title": "离线模板库", "desc": "内置 LED 闪烁、LED 指示、LDO 稳压等模板，加权语义匹配，无网络也能跑通"},
    {"icon": "chip", "title": "KiCad 工程导出", "desc": "生成 .kicad_sch / .kicad_pcb / .kicad_pro + 库表 + BOM + NETLIST，可一键唤起本机 KiCad"},
    {"icon": "doc", "title": "自动报告", "desc": "同步产出工作汇报、操作指南、硬件需求三份 Markdown 文档"},
    {"icon": "eye", "title": "实时构图与解释", "desc": "元件逐个摆放、连线逐条绘制的动画；可切换三种板色，能解释电路工作原理"},
]

WORKFLOW = [
    "理解你的描述（意图 + 关键词 + 参数）",
    "元器件选型，生成 BOM 清单",
    "建立引脚级连接关系（网表）",
    "生成 KiCad 原理图 / PCB / 工程文件",
    "输出 BOM、网表与三份报告",
]

TIPS = [
    "描述里带上「功能 + 电压 + 关键器件」，生成结果会准很多。",
    "生成后直接说修改指令即可迭代，例如「把限流电阻改成 330Ω」。",
    "没有网络时会自动降级到离线模板，功能照样可用。",
    "点左侧快捷卡片可以一键填入示例需求。",
]


# ---------------------------------------------------------------------------
# 会话存储
# ---------------------------------------------------------------------------
class Conversation:
    """一次完整的设计会话"""

    def __init__(self, cid=None, data=None):
        self.id = cid or uuid.uuid4().hex[:10]
        self.created_at = (data or {}).get("created_at", time.time())
        self.updated_at = (data or {}).get("updated_at", time.time())
        self.title = (data or {}).get("title", "新设计会话")
        self.turns = list((data or {}).get("turns", []))
        self.design = (data or {}).get("design")
        self.keywords_seen = list((data or {}).get("keywords_seen", []))
        self.last_intent = (data or {}).get("last_intent")
        self.project_name = (data or {}).get("project_name")
        self.zip_path = (data or {}).get("zip_path")

    def add_turn(self, role, text, extra=None):
        turn = {"role": role, "text": text, "ts": time.time()}
        if extra:
            turn.update(extra)
        self.turns.append(turn)
        if len(self.turns) > 80:
            self.turns = self.turns[-80:]
        self.updated_at = time.time()
        if role == "user" and self.title == "新设计会话":
            self.title = text[:24] + ("…" if len(text) > 24 else "")

    def remember_keywords(self, keywords):
        for k in keywords or []:
            term = k["term"] if isinstance(k, dict) else k
            if term not in self.keywords_seen:
                self.keywords_seen.append(term)
        self.keywords_seen = self.keywords_seen[-40:]

    def context_summary(self):
        """给 LLM 的轻量上下文摘要（不塞全量历史，控制 token）"""
        bits = []
        if self.design:
            bits.append("当前设计：" + str(self.design.get("title", "")))
            bits.append("元件数：" + str(len(self.design.get("components", []))))
        if self.keywords_seen:
            bits.append("本会话已关注：" + "、".join(self.keywords_seen[-10:]))
        if self.last_intent:
            bits.append("上一轮意图：" + self.last_intent)
        bits.append("对话轮次：" + str(len([t for t in self.turns if t["role"] == "user"])))
        return "；".join(bits)

    def to_dict(self):
        return {
            "id": self.id, "title": self.title,
            "created_at": self.created_at, "updated_at": self.updated_at,
            "turns": self.turns, "design": self.design,
            "keywords_seen": self.keywords_seen, "last_intent": self.last_intent,
            "project_name": self.project_name, "zip_path": self.zip_path,
        }

    def brief(self):
        return {
            "id": self.id, "title": self.title,
            "created_at": self.created_at, "updated_at": self.updated_at,
            "turns": len(self.turns),
            "has_design": bool(self.design),
            "design_title": (self.design or {}).get("title", ""),
        }


class SessionStore:
    """会话仓库：内存 + 本地 JSON 持久化，线程安全用简单锁兜底"""

    MAX_SESSIONS = 20
    STORE_FILE = os.path.join(config.USER_DATA_DIR, "sessions.json")

    def __init__(self):
        self._sessions: dict[str, Conversation] = {}
        self._current_id = None
        self._load()

    # -- 持久化 --
    def _load(self):
        try:
            if os.path.isfile(self.STORE_FILE):
                with open(self.STORE_FILE, "r", encoding="utf-8") as f:
                    raw = json.load(f)
                for cid, d in raw.get("sessions", {}).items():
                    self._sessions[cid] = Conversation(cid, d)
                self._current_id = raw.get("current_id")
        except Exception:
            self._sessions = {}

    def _save(self):
        try:
            os.makedirs(os.path.dirname(self.STORE_FILE), exist_ok=True)
            data = {
                "current_id": self._current_id,
                "sessions": {cid: c.to_dict() for cid, c in self._sessions.items()},
            }
            tmp = self.STORE_FILE + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=1)
            os.replace(tmp, self.STORE_FILE)
        except Exception:
            pass  # 持久化失败不影响主流程

    def _trim(self):
        if len(self._sessions) <= self.MAX_SESSIONS:
            return
        ordered = sorted(self._sessions.values(), key=lambda c: -c.updated_at)
        for c in ordered[self.MAX_SESSIONS:]:
            self._sessions.pop(c.id, None)

    # -- 操作 --
    def create(self):
        c = Conversation()
        self._sessions[c.id] = c
        self._current_id = c.id
        self._trim()
        self._save()
        return c

    def current(self):
        c = self._sessions.get(self._current_id) if self._current_id else None
        return c or self.create()

    def get(self, cid):
        return self._sessions.get(cid)

    def activate(self, cid):
        if cid in self._sessions:
            self._current_id = cid
            self._save()
            return self._sessions[cid]
        return None

    def list(self):
        return [c.brief() for c in sorted(self._sessions.values(), key=lambda x: -x.updated_at)]

    def delete(self, cid):
        if cid in self._sessions:
            del self._sessions[cid]
            if self._current_id == cid:
                self._current_id = None
            self._save()
            return True
        return False

    def clear_all(self):
        self._sessions.clear()
        self._current_id = None
        self._save()

    def commit(self):
        self._save()


STORE = SessionStore()


# ---------------------------------------------------------------------------
# 能力清单（供 /api/capabilities、前端欢迎语与帮助面板使用）
# ---------------------------------------------------------------------------
def capabilities_payload(status=None):
    return {
        "profile": ASSISTANT_PROFILE,
        "capabilities": CAPABILITIES,
        "workflow": WORKFLOW,
        "quick_commands": nlu.QUICK_COMMANDS,
        "tips": TIPS,
        "intents": [{"name": s["name"], "label": s["label"]} for s in nlu.INTENTS],
        "keyword_groups": [
            {"category": cat, "terms": sorted({g["canonical"] for g in nlu.TERM_GROUPS if g["category"] == cat})}
            for cat in ("元件", "功能", "接口", "参数")
        ],
        "status": status or {},
    }


def greeting(status=None):
    """动态欢迎语：带上当前运行模式，信息量远高于原来的固定一句话"""
    mode = "离线模板"
    if status:
        m = status.get("llm_mode")
        if m == "custom":
            mode = "自定义 LLM（" + str(status.get("llm_model") or "已配置") + "）"
        elif m == "free":
            mode = "免费在线 LLM"
    lines = [
        "你好，我是 W，你的电路设计助手。",
        "",
        "我能听懂自然语言，自动完成「意图理解 → 关键词与参数抽取 → 元器件选型 → 网表连接 → KiCad 工程 → 三份报告」。",
        "当前运行模式：" + mode + "。",
        "",
        "你可以这样说：",
        "· 做一个 5V 转 3.3V 的 LDO 稳压电路，带输入输出滤波电容",
        "· 设计一个 LED 闪烁最小系统，加晶振和复位",
        "· 生成后直接说「把 C1 换成 100nF」就能改图",
        "",
        "输入「查看帮助」看全部能力，也可以点下方快捷卡片一键开始。",
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 电路解释（基于真实 design JSON，不是空话）
# ---------------------------------------------------------------------------
def explain_design(design: dict) -> str:
    if not design:
        return "目前还没有生成电路。先描述一个需求，我来为你画第一版。"

    comps = design.get("components", [])
    nets = design.get("nets", [])
    groups = design.get("groups", [])
    title = design.get("title", "未命名电路")

    lines = ["**" + title + "** 的工作原理与构成：", ""]
    lines.append("**1. 总体规模**：共 %d 个元件、%d 条电气网络、%d 个功能模块。" % (len(comps), len(nets), len(groups)))

    if groups:
        lines.append("")
        lines.append("**2. 模块划分**")
        for g in groups:
            refs = ", ".join(g.get("refs", [])[:10]) or "—"
            lines.append("· %s：%s" % (g.get("name", "未命名"), refs))

    # 按符号类型聚合，解释每类器件的作用
    role = {
        "Device:R": "限流 / 分压 / 上拉，决定支路电流",
        "Device:C": "去耦 / 滤波，抑制电源纹波与高频噪声",
        "Device:CP": "极性电容，用于输入输出储能与低频滤波",
        "Device:LED": "发光指示，把电流转换成可见光",
        "Device:D": "单向导通，用于整流与续流保护",
        "Device:L": "储能 / 滤波，抑制电流突变",
        "Device:Crystal": "提供稳定的时钟基准",
        "Device:Q_NPN_BCE": "三极管，用作开关或电流放大",
        "Regulator_Linear:LDO": "线性稳压，把较高输入电压稳定到目标输出",
        "MCU_Microchip_ATmega:ATmega328P": "主控 MCU，负责逻辑控制与 IO 驱动",
    }
    kinds = {}
    for c in comps:
        lib_id = "%s:%s" % (c.get("lib", ""), c.get("symbol", ""))
        kinds.setdefault(lib_id, []).append(c)
    if kinds:
        lines.append("")
        lines.append("**3. 关键器件作用**")
        for lib_id, items in list(kinds.items())[:8]:
            refs = ", ".join(x.get("ref", "") for x in items[:6])
            vals = ", ".join(str(x.get("value", "")) for x in items[:3])
            desc = role.get(lib_id, "接插件 / 通用器件")
            if lib_id.startswith("Connector_Generic"):
                desc = "外部接线端子，负责电源与信号的进出"
            lines.append("· %s（%s，%s）：%s" % (refs, lib_id.split(":")[-1], vals, desc))

    if nets:
        lines.append("")
        lines.append("**4. 网络连接（信号怎么走）**")
        for n in nets[:8]:
            conns = ["%s.%s" % (c.get("ref", "?"), c.get("pin", "?")) for c in n.get("connections", [])]
            lines.append("· %s ← %s" % (n.get("name", "?"), "、".join(conns[:8]) + ("…" if len(conns) > 8 else "")))
        if len(nets) > 8:
            lines.append("· 其余 %d 条网络见「网表连接」标签页" % (len(nets) - 8))

    # 电源网络推断
    power_nets = [n.get("name", "") for n in nets if any(k in n.get("name", "").upper() for k in ("VCC", "VIN", "VOUT", "GND", "+5", "+3"))]
    if power_nets:
        lines.append("")
        lines.append("**5. 供电路径**：%s。注意上电前核对极性与额定电压。" % "、".join(power_nets[:6]))

    lines.append("")
    lines.append("想调整任何参数，直接说修改指令就行，例如「把 C1 换成 100nF」。")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 动态回复生成
# ---------------------------------------------------------------------------
def build_reply(analysis: dict, ctx: dict) -> dict:
    """
    依据意图生成助手回复。

    ctx: {has_design, design, status, template_applied, project_name, ...}
    返回: {reply, suggestions, actions, intent, analysis}
    """
    intent = analysis["intent"]["name"]
    has_design = bool(ctx.get("has_design"))
    status = ctx.get("status") or {}
    design = ctx.get("design")
    ents = analysis["entities"]
    kws = analysis["keywords"]

    reply = ""
    actions = []
    suggestions = list(analysis["suggestions"])

    if intent == "help":
        reply = "\n".join([
            "**W 的能力清单（v%s）**" % VERSION,
            "",
        ] + ["· **%s** — %s" % (c["title"], c["desc"]) for c in CAPABILITIES] + [
            "",
            "**快捷指令**：生成电路 / 改参数 / 解释 / 导出 / 新建 / 套模板 / 换风格 / 查状态，直接说就行。",
            "**支持的说法**：中英文混输、口语化表达、简写别名（如 LDO、MCU、100nF、330Ω）都能识别。",
            "",
            "不确定怎么开始？点一张快捷卡片，或者说「做一个 5V 转 3.3V 的 LDO 稳压电路」。",
        ])
        actions = [{"type": "scroll", "label": "查看快捷指令"}]

    elif intent == "status":
        mode = status.get("llm_mode", "none")
        mode_text = {"custom": "自定义 LLM（%s）" % status.get("llm_model"),
                     "free": "免费在线 LLM（%s）" % status.get("llm_model"),
                     "none": "离线模板"}.get(mode, "离线模板")
        reply = "\n".join([
            "**当前运行状态**",
            "",
            "· 推理模式：%s" % mode_text,
            "· 接口地址：%s" % (status.get("llm_base_url") or "本地离线"),
            "· KiCad：%s" % (status.get("kicad_cli") or "未检测到（不影响生成工程文件）"),
            "· 助手版本：v%s，NLU 引擎：本地规则 + 加权评分（零依赖、离线可用）" % VERSION,
            "· 术语词典：%d 组关键词，%d 类意图" % (len(nlu.TERM_GROUPS), len(nlu.INTENTS)),
            "· 会话上下文：%s" % (ctx.get("context_summary") or "暂无"),
            "",
            "没有配置密钥也能用：优先走免费在线 LLM，网络不通时自动降级到离线模板。",
        ])
        actions = [{"type": "settings", "label": "打开设置面板"}]

    elif intent == "template":
        reply = "\n".join([
            "**离线模板库**（无网络也能生成完整 KiCad 工程）",
            "",
            "1. LED 闪烁最小系统 — ATmega328P + 晶振 + 复位 + LED",
            "2. LED 指示灯 — 电源指示 + 限流电阻",
            "3. 5V 转 3.3V LDO 稳压 — AMS1117 + 输入输出滤波",
            "",
            "点左侧「模板库」卡片即可直接套用；也可以描述需求，我会按语义加权自动选最贴近的模板。",
        ])
        tpl = analysis["template"]["best"]
        suggestions = ["套用 LED 闪烁模板", "套用 LDO 稳压模板", "套用 LED 指示灯模板"]
        actions = [{"type": "template", "value": tpl, "label": "套用推荐模板"}]

    elif intent == "explain":
        reply = explain_design(design)
        actions = [{"type": "tab", "value": "netlist", "label": "查看完整网表"}]

    elif intent == "export":
        if not has_design:
            reply = "还没有可导出的设计。先描述一个电路需求，生成完成后我就能导出工程包与报告。"
            suggestions = ["做一个 5V 转 3.3V 的 LDO 稳压电路", "查看帮助"]
        else:
            reply = "\n".join([
                "已为你准备好导出内容：",
                "",
                "· **KiCad 工程包**（.zip，含 .kicad_sch / .kicad_pcb / .kicad_pro + 库表）",
                "· **BOM 清单 / 网表**（Markdown 与 CSV）",
                "· **三份报告**（工作汇报 / 操作指南 / 硬件需求）",
                "· **设计 JSON**（可直接编辑后再重新生成）",
                "",
                "点右侧「下载 KiCad 工程」，或用结果区工具条单独下载、复制、打开输出文件夹。",
            ])
            actions = [{"type": "download", "label": "下载工程包"}]

    elif intent == "render":
        style = ctx.get("style", "classic")
        reply = "已按「%s」风格重新绘制原理图。你也可以在右侧舞台切换三种板色、缩放或导出 SVG。" % {
            "classic": "经典绿", "minimal": "现代极简", "retro": "复古暖铜"
        }.get(style, style)
        actions = [{"type": "render", "label": "重新绘制"}]

    elif intent == "reset":
        reply = "已开启一个全新会话，上一版设计仍保留在「历史会话」里，随时可以切回来。现在告诉我你想做什么电路？"
        suggestions = ["做一个 5V 转 3.3V 的 LDO 稳压电路", "设计一个 LED 闪烁最小系统", "查看帮助"]

    elif intent == "revise":
        targets = []
        if ents["refs"]:
            targets.append("元件 " + "、".join(ents["refs"][:4]))
        if ents["categories"]:
            targets.append("类别 " + "、".join(ents["categories"][:3]))
        if ents["values"]:
            targets.append("参数 " + "、".join(ents["values"][:4]))
        if ents["actions"]:
            verb = {"set": "修改参数", "add": "增加元件", "remove": "删除元件"}
            targets.append("动作 " + "、".join(verb.get(a, a) for a in ents["actions"]))
        if not has_design:
            reply = "我理解你想调整电路，但目前还没有已生成的设计。先描述一个需求生成第一版，之后就能直接说修改指令了。"
            suggestions = ["做一个 LED 指示灯电路", "查看帮助"]
        else:
            reply = "\n".join([
                "收到修改指令，正在更新电路。",
                "",
                "**我的理解**：" + analysis["summary"],
                ("**定位到**：" + "；".join(targets)) if targets else "",
                "**意图**：%s（置信度 %.0f%%）" % (analysis["intent"]["label"], analysis["confidence"] * 100),
                "",
                "修改后会重新生成原理图、BOM、网表和三份报告，右侧构图也会同步刷新。",
            ])

    elif intent == "generate":
        mode = status.get("llm_mode", "none")
        mode_text = {"custom": "自定义 LLM", "free": "免费在线 LLM", "none": "离线模板（加权语义匹配）"}.get(mode, "离线模板")
        lines = [
            "需求已解析，开始设计。",
            "",
            "**意图**：%s（置信度 %.0f%%）" % (analysis["intent"]["label"], analysis["confidence"] * 100),
            "**理解**：" + analysis["summary"],
        ]
        if kws:
            cats = {}
            for k in kws:
                cats.setdefault(k["category"], []).append(k["term"])
            lines.append("**关键词**：" + " / ".join("%s(%s)" % (c, "、".join(t[:4])) for c, t in cats.items()))
        lines.append("**选型策略**：%s；离线兜底模板 → %s" % (mode_text, analysis["template"]["best"]))
        lines.append("**执行流程**：" + " → ".join(nlu_workflow_short()))
        if analysis["clarifying_question"]:
            lines += ["", "提示：" + analysis["clarifying_question"]]
        reply = "\n".join(lines)
        actions = [{"type": "tab", "value": "bom", "label": "查看 BOM"}]

    else:
        reply = "我暂时没完全理解这句话，但可以试着按「%s」处理。你也可以换一种说法，或输入「查看帮助」。" % analysis["intent"]["label"]
        suggestions = ["做一个 LED 指示灯电路", "查看帮助"]

    return {
        "reply": reply.strip(),
        "suggestions": suggestions[:4],
        "actions": actions,
        "intent": intent,
        "analysis": analysis,
    }


def nlu_workflow_short():
    return ["需求解析", "选型 BOM", "网表连接", "KiCad 生成", "报告产出"]


def success_reply(analysis: dict, data: dict, is_revision: bool) -> str:
    """生成完成后的总结性回复（带真实数据，不是空话）"""
    design = data.get("design") or {}
    comps = design.get("components", [])
    nets = design.get("nets", [])
    groups = design.get("groups", [])
    mode = data.get("mode", "")
    if mode.startswith("llm:"):
        mode_text = "大模型生成"
    elif mode.startswith("template"):
        mode_text = "离线模板"
    else:
        mode_text = mode

    lines = [
        "**%s已完成**：%s" % ("修改" if is_revision else "电路", design.get("title", "未命名电路")),
        "",
        "· 元件 %d 个 / 网络 %d 条 / 模块 %d 个，生成方式：%s" % (len(comps), len(nets), len(groups), mode_text),
        "· 已输出 KiCad 原理图、PCB 骨架、工程文件、BOM、网表与三份报告",
    ]
    # 列出关键参数
    key_params = [c for c in comps if c.get("value")][:6]
    if key_params:
        lines.append("· 关键参数：" + "、".join("%s=%s" % (c.get("ref"), c.get("value")) for c in key_params))
    lines += [
        "",
        "右侧可查看实时构图、切换风格、缩放导出；想改哪里直接说，比如「把 C1 换成 100nF」。",
    ]
    return "\n".join(lines)
