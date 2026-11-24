# -*- coding: utf-8 -*-
"""
跨轮需求档案（Dialogue Requirement Profile）
============================================

解决"从日常对话里听懂电路需求"的问题：

单句 NLU（nlu.analyze）只能理解当下这一句。但真实对话里，需求是散落在多轮里的：
    "我最近在搞个温度采集的东西"
    "传感器用 DHT11 吧"
    "供电是 3.3V，数据线拉个上拉"

本模块把每一轮抽取到的功能/器件/参数/接口累积成一份「需求档案」，
并判断信息是否足够完整到可以直接出图，或从日常闲聊里识别出隐含的绘图意图。

设计原则：纯标准库、离线可用、复用 nlu 的词表与实体抽取，绝不依赖 LLM。
"""

from __future__ import annotations

import re
import time

from . import nlu

# 需求槽位：功能 / 器件 / 接口 / 参数 / 电压 / 供电 / 约束
SLOTS = ("function", "component", "interface", "param", "voltage", "power", "constraint")

# 一份需求档案"可出图"的最低要求：至少有 1 个功能或器件信号
_MIN_SIGNALS = 2


class RequirementProfile:
    """一次会话内累积的结构化需求（可序列化进 Conversation）"""

    def __init__(self, data: dict | None = None):
        data = data or {}
        self.slots: dict[str, list[str]] = {}
        for key in SLOTS:
            self.slots[key] = list(data.get("slots", {}).get(key, []))
        self.raw_phrases: list[str] = list(data.get("raw_phrases", []))[-12:]
        self.updated_at: float = data.get("updated_at", time.time())
        self.confirmed: bool = bool(data.get("confirmed", False))
        self.last_summary: str = data.get("last_summary", "")

    # ---------- 累积 ----------
    def _add(self, slot: str, value: str):
        value = str(value).strip()
        if value and value not in self.slots[slot]:
            self.slots[slot].append(value)
            if len(self.slots[slot]) > 16:
                self.slots[slot] = self.slots[slot][-16:]

    def absorb(self, analysis: dict, message: str = "") -> bool:
        """吸收一轮 NLU 结果。返回 True 表示档案有实质更新。"""
        before = sum(len(v) for v in self.slots.values())
        ents = analysis.get("entities", {}) or {}
        for k in analysis.get("keywords", []) or []:
            cat = k.get("category")
            term = k.get("term")
            mapping = {"功能": "function", "元件": "component", "接口": "interface",
                       "参数": "param"}
            if cat in mapping:
                self._add(mapping[cat], term)
        for key, slot in (("voltage", "voltage"), ("resistance", "param"),
                          ("capacitance", "param"), ("frequency", "param"),
                          ("quantity", "constraint"), ("nets", "interface")):
            for v in ents.get(key, []) or []:
                self._add(slot, v)
        if message and len(self.slots["function"] + self.slots["component"]) >= 1:
            # 只记录含电路信号的话，避免把纯闲聊塞进档案
            phrase = message.strip()[:60]
            if phrase and phrase not in self.raw_phrases:
                self.raw_phrases.append(phrase)
                self.raw_phrases = self.raw_phrases[-12:]
        self.updated_at = time.time()
        return sum(len(v) for v in self.slots.values()) != before

    def signal_count(self) -> int:
        """硬件信号强度：功能 + 器件 + 接口 三类去重计数"""
        return len(set(self.slots["function"]) | set(self.slots["component"]) | set(self.slots["interface"]))

    def completeness(self) -> dict:
        """需求完整度：给出 0~100 分、缺失槽位与一句提示"""
        score = 0
        reasons = []
        if self.slots["function"]:
            score += 30
        else:
            reasons.append("想实现什么功能（闪烁 / 稳压 / 采集 …）")
        if self.slots["component"]:
            score += 30
        else:
            reasons.append("关键器件（如 DHT11 / NE555 / AMS1117）")
        if self.slots["voltage"] or self.slots["power"]:
            score += 20
        else:
            reasons.append("供电电压（如 5V / 3.3V）")
        if self.slots["param"] or self.slots["interface"] or self.slots["constraint"]:
            score += 20
        else:
            reasons.append("接口或参数（限流阻值 / 上拉 / 通信接口 …）")
        return {"score": score, "missing": reasons, "ready": self.signal_count() >= _MIN_SIGNALS}

    def to_summary(self) -> str:
        """把档案拼成一句人话："我从对话里听懂你要的是…" """
        parts = []
        label = {"function": "功能", "component": "器件", "interface": "接口",
                 "voltage": "电压", "param": "参数", "constraint": "要求"}
        for key in ("function", "component", "interface", "voltage", "param", "constraint"):
            vals = self.slots.get(key, [])
            if vals:
                parts.append("%s：%s" % (label[key], "、".join(vals[:4])))
        if not parts:
            return "还没听出明确的电路需求，可以继续描述你要做的东西。"
        return "；".join(parts) + "。"

    def to_dict(self) -> dict:
        return {
            "slots": {k: list(v) for k, v in self.slots.items()},
            "raw_phrases": list(self.raw_phrases),
            "updated_at": self.updated_at,
            "confirmed": self.confirmed,
            "last_summary": self.last_summary,
        }

    def brief(self) -> dict:
        c = self.completeness()
        return {
            "summary": self.to_summary(),
            "completeness": c["score"],
            "missing": c["missing"],
            "ready": c["ready"],
            "signals": self.signal_count(),
            "confirmed": self.confirmed,
        }


# ---------------------------------------------------------------------------
# 隐含意图：从日常对话里识别"其实想让我画板子"
# ---------------------------------------------------------------------------
# 这些是"确认/触发出图"的说法，命中后即使没有"做一个"也会生成
_CONFIRM_WORDS = (
    "画吧", "就这个", "就这样", "开始画", "生成吧", "按这个做", "按上面",
    "来吧", "出图", "绘制", "可以画", "就这么定", "开始设计", "do it",
)
# 这些是明确的闲聊/非设计话题，命中则不触发
_CHITCHAT_WORDS = (
    "你好", "在吗", "谢谢", "再见", "天气", "今天", "搞笑", "讲个笑话",
    "你是谁", "吃什么", "几点了",
)


def wants_design(message: str, analysis: dict, profile: RequirementProfile,
                 has_design: bool = False) -> tuple[bool, str]:
    """
    判断一句话（结合累积档案）是否隐含绘图需求。

    返回 (是否出图, 依据说明)。规则优先级：
      1. NLU 明确判 generate/revise → 是
      2. 命中确认词（"画吧"/"就这个"）且档案有信号 → 是
      3. 明确闲聊且无信号 → 否
      4. 单句虽无动词，但本轮新增的硬件信号 ≥ 2 → 是（"DHT11 温湿度，3.3V 供电"）
    """
    text = str(message or "")
    intent_obj = analysis.get("intent") or {}
    intent = intent_obj.get("name", "")
    is_fallback = bool(intent_obj.get("fallback"))
    # 1. 明确的设计指令（非兜底）优先
    if intent in ("generate", "revise") and not is_fallback:
        return True, "明确的设计指令"
    # 2. 确认词 + 档案有信号 → 出图
    if any(w in text for w in _CONFIRM_WORDS) and profile.signal_count() >= _MIN_SIGNALS:
        profile.confirmed = True
        return True, "确认按累积需求出图"
    # 3. 明确闲聊且档案信号不够 → 不出图
    if any(w in text for w in _CHITCHAT_WORDS) and profile.signal_count() < _MIN_SIGNALS:
        return False, "闲聊"
    # 4. 兜底的 generate 不算明确指令，继续按信号判断
    kws = analysis.get("keywords", []) or []
    new_signals = {k["term"] for k in kws if k.get("category") in ("功能", "元件", "接口")}
    if len(new_signals) >= _MIN_SIGNALS:
        return True, "单句含多个硬件信号"
    if profile.completeness()["ready"] and re.search(
            r"(还有|另外|加|要|需要|用|带|的话|吧|了)$|度|采集|供电|驱动|模块|电路|板子", text):
        return profile.confirmed or profile.signal_count() >= 3, "累积需求已较完整"
    return False, "信息不足，继续累积"


def build_digest(profile: RequirementProfile, message: str = "") -> dict:
    """生成给前端展示的需求理解卡：我听懂了什么 + 还缺什么 + 能不能出图"""
    brief = profile.brief()
    brief["hint"] = (
        "我已经从我们的对话里拼出一份需求，确认无误就说「画吧」；"
        "也可以继续补充细节。"
        if brief["ready"] and not brief["confirmed"] else
        ("需求还差一点：" + "、".join(brief["missing"][:2]) + "，补充后我就能出图。"
         if brief["missing"] else "")
    )
    return brief


def merge_into_requirement(profile: RequirementProfile, fallback: str = "自定义电路") -> str:
    """把累积档案拼成一段可喂给生成器的需求描述（用于 LLM / 模板匹配）"""
    s = profile.to_summary()
    if not s or "还没听出" in s:
        return fallback
    return s
