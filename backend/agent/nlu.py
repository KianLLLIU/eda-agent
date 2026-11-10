# -*- coding: utf-8 -*-
"""
自然语言理解引擎（NLU）
=========================

把「一句话需求」解析成结构化信息，供对话助手、离线模板匹配、LLM Prompt 共用。

三层能力：
  1. 意图分类   —— generate / revise / explain / export / template / help /
                   status / reset / render / unknown（中英文关键词 + 正则 + 加权评分）
  2. 实体抽取   —— 元件类别、元件编号、参数值（阻值/容值/电压/频率）、数量、动作动词
  3. 关键词识别 —— 分组同义词词典 + 归一化 + 模糊匹配 + 权重，输出带类别的结构化词

设计原则：纯标准库、离线可用、零依赖、可被 LLM 增强但绝不依赖 LLM。
这样即使在内网 / 无 API Key / 免费模型不可用的情况下，助手依然「听得懂人话」。
"""

from __future__ import annotations

import re
from difflib import SequenceMatcher

# ---------------------------------------------------------------------------
# 一、关键词词典（分组 · 同义词 · 权重）
# ---------------------------------------------------------------------------
# canonical 是归一化后的标准词，前端高亮与 LLM Prompt 都用它。
# weight 越高越能代表用户真实意图（功能词 > 泛化词）。
TERM_GROUPS = [
    # ---- 元件 ----
    {"canonical": "电阻", "category": "元件", "weight": 2,
     "aliases": ["电阻", "resistor", "限流电阻", "上拉电阻", "下拉电阻", "r"]},
    {"canonical": "电容", "category": "元件", "weight": 2,
     "aliases": ["电容", "capacitor", "去耦电容", "旁路电容", "滤波电容", "电解电容", "c"]},
    {"canonical": "LED", "category": "元件", "weight": 3,
     "aliases": ["led", "发光二极管", "led灯", "leds", "light emitting diode", "灯珠"]},
    {"canonical": "二极管", "category": "元件", "weight": 2,
     "aliases": ["二极管", "diode", "整流二极管", "肖特基", "续流二极管"]},
    {"canonical": "电感", "category": "元件", "weight": 2,
     "aliases": ["电感", "inductor", "线圈", "磁珠"]},
    {"canonical": "晶振", "category": "元件", "weight": 2,
     "aliases": ["晶振", "晶体", "crystal", "oscillator", "时钟源", "外部晶振"]},
    {"canonical": "三极管", "category": "元件", "weight": 2,
     "aliases": ["三极管", "晶体管", "npn", "mos管", "mosfet", "transistor", "场效应管"]},
    {"canonical": "稳压器", "category": "元件", "weight": 3,
     "aliases": ["ldo", "稳压器", "稳压芯片", "线性稳压", "ams1117", "lm7805", "regulator"]},
    {"canonical": "单片机", "category": "元件", "weight": 3,
     "aliases": ["单片机", "mcu", "微控制器", "arduino", "atmega", "atmega328p", "stm32",
                 "esp32", "主控", "处理器", "microcontroller"]},
    {"canonical": "接插件", "category": "元件", "weight": 2,
     "aliases": ["排针", "排母", "接插件", "连接器", "端子", "connector", "pinheader",
                 "接口", "插座", "header"]},
    {"canonical": "按键", "category": "元件", "weight": 2,
     "aliases": ["按键", "按钮", "开关", "button", "switch", "轻触开关"]},
    {"canonical": "蜂鸣器", "category": "元件", "weight": 2,
     "aliases": ["蜂鸣器", "buzzer", "报警器"]},
    {"canonical": "传感器", "category": "元件", "weight": 2,
     "aliases": ["传感器", "sensor", "温湿度", "温度", "dht", "光敏", "adc采样"]},

    # ---- 功能 ----
    {"canonical": "闪烁", "category": "功能", "weight": 5,
     "aliases": ["闪烁", "闪灯", "一闪一闪", "呼吸灯", "blink", "flash", "流水灯", "频闪"]},
    {"canonical": "指示灯", "category": "功能", "weight": 5,
     "aliases": ["指示灯", "状态灯", "电源指示", "indicator", "指示", "发光指示"]},
    {"canonical": "稳压", "category": "功能", "weight": 5,
     "aliases": ["稳压", "降压", "升压", "电平转换", "ldo", "regulator", "buck", "boost",
                 "dc-dc", "dcdc", "电压转换", "5v转3.3v"]},
    {"canonical": "电源", "category": "功能", "weight": 3,
     "aliases": ["电源", "供电", "power", "supply", "vcc", "gnd", "地线", "参考地"]},
    {"canonical": "去耦滤波", "category": "功能", "weight": 3,
     "aliases": ["去耦", "滤波", "旁路", "decoupling", "bypass", "rc滤波", "低通", "抗干扰"]},
    {"canonical": "复位", "category": "功能", "weight": 3,
     "aliases": ["复位", "reset", "上电复位", "重启电路"]},
    {"canonical": "最小系统", "category": "功能", "weight": 4,
     "aliases": ["最小系统", "核心板", "最小电路", "minimum system", "主控电路"]},
    {"canonical": "限流", "category": "功能", "weight": 3,
     "aliases": ["限流", "分压", "偏置", "current limit", "上拉", "下拉"]},
    {"canonical": "驱动", "category": "功能", "weight": 3,
     "aliases": ["驱动", "drive", "电机驱动", "继电器", "mos驱动"]},
    {"canonical": "充电", "category": "功能", "weight": 3,
     "aliases": ["充电", "charge", "锂电池", "tp4056", "电池管理"]},

    # ---- 接口 / 通信 ----
    {"canonical": "I2C", "category": "接口", "weight": 3,
     "aliases": ["i2c", "iic", "twi", "两线"]},
    {"canonical": "SPI", "category": "接口", "weight": 3,
     "aliases": ["spi", "串行外设"]},
    {"canonical": "UART", "category": "接口", "weight": 3,
     "aliases": ["uart", "串口", "usart", "ttl串口", "rs232", "rs485"]},
    {"canonical": "USB", "category": "接口", "weight": 3,
     "aliases": ["usb", "type-c", "typec", "microusb"]},
    {"canonical": "GPIO", "category": "接口", "weight": 2,
     "aliases": ["gpio", "io口", "引脚", "pwm", "adc", "dac"]},

    # ---- 参数 ----
    {"canonical": "电压", "category": "参数", "weight": 2,
     "aliases": ["电压", "voltage", "伏", "v"]},
    {"canonical": "阻值", "category": "参数", "weight": 2,
     "aliases": ["阻值", "欧姆", "ω", "ohm", "ω"]},
    {"canonical": "容值", "category": "参数", "weight": 2,
     "aliases": ["容值", "微法", "纳法", "皮法", "farad"]},
    {"canonical": "频率", "category": "参数", "weight": 2,
     "aliases": ["频率", "时钟", "mhz", "khz", "hz", "兆赫"]},
]

# ---------------------------------------------------------------------------
# 二、意图定义（关键词 + 正则 + 权重）
# ---------------------------------------------------------------------------
INTENTS = [
    {
        "name": "help", "label": "查看帮助", "weight": 3,
        "keywords": ["帮助", "怎么用", "能做什么", "使用说明", "功能介绍", "help", "commands",
                     "指令", "支持什么", "会什么", "hi", "hello", "你好", "嗨"],
        "patterns": [r"^\s*(help|/help|\?|？)\s*$"],
    },
    {
        "name": "status", "label": "查询状态", "weight": 3,
        "keywords": ["状态", "配置", "当前模式", "用了什么模型", "status", "版本", "version",
                     "运行环境", "llm状态"],
        "patterns": [],
    },
    {
        "name": "template", "label": "套用模板", "weight": 4,
        "keywords": ["模板", "套用", "示例电路", "template", "预设", "用现成的", "加载模板"],
        "patterns": [r"(用|加载|套用|打开)\s*(第?\s*\d+\s*个)?\s*模板"],
    },
    {
        "name": "explain", "label": "解释电路", "weight": 3,
        "keywords": ["解释", "说明", "为什么", "讲一下", "原理", "分析", "是什么意思",
                     "explain", "why", "这批元件", "怎么工作", "工作原理"],
        "patterns": [],
    },
    {
        "name": "export", "label": "导出文件", "weight": 3,
        "keywords": ["导出", "下载", "保存", "export", "download", "打包", "zip",
                     "生成报告", "打开文件夹", "输出目录"],
        "patterns": [],
    },
    {
        "name": "render", "label": "重新绘图", "weight": 3,
        "keywords": ["重绘", "重新画", "换个风格", "刷新构图", "重播", "render",
                     "切换风格", "重新渲染"],
        "patterns": [],
    },
    {
        "name": "reset", "label": "新建设计", "weight": 4,
        "keywords": ["新建", "重来", "清空", "重置", "reset", "clear", "从头开始",
                     "换个电路", "重新开始", "新对话"],
        "patterns": [r"^\s*(/reset|/new|/clear)\s*$"],
    },
    {
        "name": "revise", "label": "修改电路", "weight": 3,
        "keywords": ["换成", "改为", "改成", "替换", "修改", "调整", "增加", "添加", "加上",
                     "删除", "去掉", "移除", "删掉", "设为", "改成", "改一下", "再",
                     "change", "replace", "modify", "add", "remove", "delete", "set"],
        "patterns": [
            r"(把|将)\s*.{0,20}\s*(换成|改为|改成|设为|调整为)",
            r"(增加|添加|加上|删掉|删除|去掉|移除)\s*.{0,20}",
            r"^\s*(再|另外|还有)\s*.+",
        ],
    },
    {
        "name": "generate", "label": "生成电路", "weight": 2,
        "keywords": ["生成", "设计", "画", "做一个", "来一个", "搭建", "构建", "需要",
                     "想要", "做一个", "帮我做", "create", "design", "generate", "build",
                     "电路", "原理图", "pcb", "schematic"],
        "patterns": [],
    },
]

# 快捷指令（前端快捷卡片 / 帮助文本共用）
QUICK_COMMANDS = [
    {"group": "生成电路", "icon": "bolt", "text": "做一个 5V 转 3.3V 的 LDO 稳压电路，带输入输出滤波电容", "label": "LDO 稳压电源"},
    {"group": "生成电路", "icon": "bolt", "text": "设计一个 LED 闪烁电路，用 ATmega328P 最小系统驱动", "label": "LED 闪烁最小系统"},
    {"group": "生成电路", "icon": "bolt", "text": "画一个带限流电阻的 LED 电源指示灯", "label": "LED 指示灯"},
    {"group": "生成电路", "icon": "bolt", "text": "做一个带去耦电容和复位电路的 STM32 最小系统", "label": "MCU 最小系统"},
    {"group": "修改电路", "icon": "edit", "text": "把 C1 换成 100nF", "label": "改电容容值"},
    {"group": "修改电路", "icon": "edit", "text": "把限流电阻改成 330 欧姆", "label": "改电阻阻值"},
    {"group": "修改电路", "icon": "edit", "text": "增加一组 100nF 去耦电容", "label": "增加去耦电容"},
    {"group": "其他操作", "icon": "help", "text": "解释一下当前电路的工作原理", "label": "解释电路"},
    {"group": "其他操作", "icon": "help", "text": "查看帮助", "label": "查看能力"},
    {"group": "其他操作", "icon": "help", "text": "导出当前设计的 Markdown 报告", "label": "导出报告"},
]

# ---------------------------------------------------------------------------
# 三、离线模板信号（加权评分，替代原先「首个关键词命中」）
# ---------------------------------------------------------------------------
TEMPLATE_SIGNALS = {
    "led_blink": [
        ("闪烁", 6), ("blink", 6), ("闪灯", 5), ("呼吸灯", 5), ("流水灯", 5),
        ("一闪一闪", 5), ("flash", 4), ("最小系统", 4), ("atmega", 4), ("arduino", 4),
        ("单片机", 3), ("mcu", 3), ("晶振", 2), ("复位", 2),
    ],
    "led_indicator": [
        ("指示灯", 6), ("状态灯", 5), ("indicator", 5), ("电源指示", 5),
        ("led", 4), ("发光", 4), ("限流", 4), ("发光二极管", 3), ("led灯", 3),
        ("分压", 1), ("电阻", 1),
    ],
    "ldo_3v3": [
        ("稳压", 7), ("ldo", 7), ("降压", 6), ("3.3", 6), ("3v3", 6),
        ("电平转换", 5), ("ams1117", 5), ("电压转换", 5), ("regulator", 5),
        ("电源", 3), ("滤波", 3), ("去耦", 3), ("5v", 2), ("供电", 2),
    ],
}

# ---------------------------------------------------------------------------
# 四、实体抽取正则
# ---------------------------------------------------------------------------
RE_RESISTANCE = re.compile(r"(\d+(?:\.\d+)?)\s*(k\s*Ω|k\s*ohm|kω|kΩ|k|K|MΩ|M|R|Ω|欧姆|欧)", re.I)
RE_CAPACITANCE = re.compile(r"(\d+(?:\.\d+)?)\s*(µF|uF|uf|nF|nf|pF|pf|mF|微法|纳法|皮法)", re.I)
RE_VOLTAGE = re.compile(r"(\d+(?:\.\d+)?)\s*(V|v|伏特|伏)")
RE_FREQUENCY = re.compile(r"(\d+(?:\.\d+)?)\s*(MHz|mhz|kHz|khz|GHz|Hz|兆赫|赫兹)")
RE_REF = re.compile(r"\b([A-Z]{1,4}\d{1,3})\b")
RE_QUANTITY = re.compile(r"(\d+)\s*(个|只|路|颗|片|组|路)")
RE_NET = re.compile(r"网络\s*([A-Za-z_][A-Za-z0-9_]*)")
RE_ANY_VALUE = re.compile(r"\d+(?:\.\d+)?\s*(?:µF|uF|uf|nF|nf|pF|pf|mF|kΩ|kohm|k|MΩ|M|R|Ω|V|v|MHz|kHz|Hz|欧姆|欧|微法|纳法|皮法|伏)")

ACTION_WORDS = {
    "set": ["换成", "改为", "改成", "设为", "替换为", "替换成", "调整为", "调成", "change", "replace", "set"],
    "add": ["增加", "添加", "加上", "加一个", "新增", "补充", "add", "insert"],
    "remove": ["删除", "去掉", "移除", "删掉", "不要", "remove", "delete"],
}

# 类别 → 元件编号前缀 / lib_id 关键词（用于离线修改定位元件）
CATEGORY_TO_SYMBOL = {
    "电阻": ["Device:R"],
    "电容": ["Device:C", "Device:CP"],
    "LED": ["Device:LED"],
    "二极管": ["Device:D"],
    "电感": ["Device:L"],
    "晶振": ["Device:Crystal"],
    "三极管": ["Device:Q_NPN_BCE"],
    "稳压器": ["Regulator_Linear:LDO"],
    "单片机": ["MCU_Microchip_ATmega:ATmega328P"],
    "接插件": ["Connector_Generic"],
}


# ---------------------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------------------
def _normalize(text: str) -> str:
    """归一化：全角转半角、大小写、去掉多余空白与常见标点"""
    if not text:
        return ""
    s = str(text).strip().lower()
    s = s.translate(_FULLWIDTH_TABLE)
    s = re.sub(r"\s+", " ", s)
    return s


_FULLWIDTH_TABLE = str.maketrans({
    "，": ",", "。": ".", "！": "!", "？": "?", "；": ";", "：": ":",
    "（": "(", "）": ")", "【": "[", "】": "]", "「": '"', "」": '"',
    "＂": '"', "“": '"', "”": '"', "、": ",", "．": ".",
    "％": "%", "＋": "+", "－": "-", "～": "~", "　": " ",
})


def _fuzzy_hit(token: str, alias: str) -> bool:
    """英文长词的模糊匹配（容忍 1~2 个拼写错误），中文用 2-gram 相似度"""
    if len(alias) < 5 or not re.fullmatch(r"[a-z0-9\-\. ]+", alias):
        return False
    if len(token) < 4:
        return False
    # 长词允许 2 字符编辑距离，用 SequenceMatcher 做近似判断
    ratio = SequenceMatcher(None, token, alias).ratio()
    return ratio >= (0.86 if len(alias) >= 7 else 0.9)


def recognize_keywords(text: str) -> list[dict]:
    """识别关键词，返回 [{'term','category','matched','weight'}, ...]（按权重降序）"""
    norm = _normalize(text)
    tokens = set(re.findall(r"[a-z0-9\-\.]+", norm))
    hits: dict[str, dict] = {}

    for group in TERM_GROUPS:
        canonical = group["canonical"]
        best_alias = None
        for alias in group["aliases"]:
            a = alias.lower()
            if len(a) <= 2 and re.fullmatch(r"[a-z0-9]+", a):
                # 短英文别名必须按词边界匹配，避免 "c" 命中所有含 c 的单词
                if re.search(r"\b" + re.escape(a) + r"\b", norm):
                    best_alias = alias
                    break
            elif a in norm:
                best_alias = alias
                break
        if best_alias is None:
            # 模糊匹配兜底（拼写错误 / 复数 / 连字符变体）
            for alias in group["aliases"]:
                if any(_fuzzy_hit(t, alias.lower()) for t in tokens):
                    best_alias = alias
                    break
        if best_alias:
            hits[canonical] = {
                "term": canonical,
                "category": group["category"],
                "matched": best_alias,
                "weight": group["weight"],
            }

    return sorted(hits.values(), key=lambda x: -x["weight"])


def extract_entities(text: str) -> dict:
    """抽取元件编号、参数值、数量、网络名、动作等实体"""
    raw = str(text or "")
    ents: dict = {
        "refs": [], "values": [], "resistance": [], "capacitance": [],
        "voltage": [], "frequency": [], "quantity": [], "nets": [],
        "actions": [], "categories": [],
    }

    for m in RE_REF.finditer(raw):
        if m.group(1) not in ents["refs"]:
            ents["refs"].append(m.group(1))
    for key, regex in (("resistance", RE_RESISTANCE), ("capacitance", RE_CAPACITANCE),
                       ("voltage", RE_VOLTAGE), ("frequency", RE_FREQUENCY),
                       ("quantity", RE_QUANTITY)):
        for m in regex.finditer(raw):
            val = m.group(0).strip()
            if val not in ents[key]:
                ents[key].append(val)
    for m in RE_NET.finditer(raw):
        if m.group(1) not in ents["nets"]:
            ents["nets"].append(m.group(1))
    for m in RE_ANY_VALUE.finditer(raw):
        v = m.group(0).strip()
        if v not in ents["values"]:
            ents["values"].append(v)
    for action, words in ACTION_WORDS.items():
        if any(w in _normalize(raw) for w in words):
            ents["actions"].append(action)
    for kw in recognize_keywords(raw):
        if kw["category"] == "元件" and kw["term"] in CATEGORY_TO_SYMBOL:
            ents["categories"].append(kw["term"])
    return ents


def classify_intent(text: str, has_design: bool = False) -> dict:
    """加权意图分类，返回 {name, label, score, confidence, matched}"""
    norm = _normalize(text)
    scores: dict[str, dict] = {}
    for spec in INTENTS:
        score = 0
        matched = []
        for kw in spec["keywords"]:
            k = kw.lower()
            if len(k) <= 2 and re.fullmatch(r"[a-z0-9]+", k):
                hit = bool(re.search(r"\b" + re.escape(k) + r"\b", norm))
            else:
                hit = k in norm
            if hit:
                score += 1
                matched.append(kw)
        for pat in spec["patterns"]:
            if re.search(pat, raw_text(text), re.I):
                score += 2
                matched.append("正则:" + pat)
        if score:
            score += spec["weight"]
            scores[spec["name"]] = {
                "name": spec["name"], "label": spec["label"],
                "score": score, "matched": matched[:6],
            }

    if scores:
        best = max(scores.values(), key=lambda x: x["score"])
    else:
        best = {"name": "", "label": "", "score": 0, "matched": []}

    # 没有命中任何意图时：已有设计 → 默认为修改；否则 → 生成
    if not best["name"]:
        best = {
            "name": "revise" if has_design else "generate",
            "label": "修改电路" if has_design else "生成电路",
            "score": 0, "matched": [], "fallback": True,
        }

    # 修改类意图必须有现存设计；否则降级为生成（避免「我想设计一个…改成…」误判）
    if best["name"] == "revise" and not has_design:
        gen = scores.get("generate", {})
        if gen.get("score", 0) >= 5:
            best = gen

    conf = 0.52 + min(best["score"], 12) * 0.035
    if best.get("fallback"):
        conf = 0.55
    best["confidence"] = round(min(conf, 0.98), 2)
    return best


def raw_text(text) -> str:
    return str(text or "")


def match_template(text: str) -> tuple[str, list[dict]]:
    """加权模板匹配，返回 (最佳模板名, 候选列表含分数)"""
    norm = _normalize(text)
    ranked = []
    for name, signals in TEMPLATE_SIGNALS.items():
        score = 0
        hit_terms = []
        for term, weight in signals:
            if term.lower() in norm:
                score += weight
                hit_terms.append(term)
        ranked.append({"name": name, "score": score, "matched": hit_terms[:6]})
    ranked.sort(key=lambda x: -x["score"])
    best = ranked[0]
    # 完全没有信号时给一个默认模板
    if best["score"] == 0:
        best = {"name": "led_indicator", "score": 0, "matched": []}
        ranked[0] = best
    return best["name"], ranked


def _describe(analysis: dict) -> str:
    """生成一句「我理解成…」的自然语言摘要，用于助手回显"""
    parts = []
    ents = analysis["entities"]
    kws = analysis["keywords"]
    functional = [k["term"] for k in kws if k["category"] == "功能"][:3]
    components = [k["term"] for k in kws if k["category"] == "元件"][:3]
    interfaces = [k["term"] for k in kws if k["category"] == "接口"][:3]

    if functional:
        parts.append("功能：" + "、".join(functional))
    if components:
        parts.append("器件：" + "、".join(components))
    if interfaces:
        parts.append("接口：" + "、".join(interfaces))
    if ents["voltage"]:
        parts.append("电压：" + "、".join(ents["voltage"][:3]))
    if ents["values"]:
        parts.append("参数：" + "、".join(ents["values"][:3]))
    if ents["refs"]:
        parts.append("目标元件：" + "、".join(ents["refs"][:4]))
    return "；".join(parts) if parts else "暂未识别到明确的电路术语，我会按通用描述处理"


def _suggestions(analysis: dict, has_design: bool) -> list[str]:
    """基于识别结果生成下一步建议（前端渲染成可点击 chips）"""
    intent = analysis["intent"]["name"]
    kws = {k["term"] for k in analysis["keywords"]}
    out = []
    if intent in ("generate", "unknown"):
        if not kws:
            out.append("补一句功能，例如「做一个 5V 转 3.3V 稳压电路」")
        if "电压" not in kws and not analysis["entities"]["voltage"]:
            out.append("指定供电电压（如 5V / 3.3V）")
        if "LED" in kws:
            out.append("加上限流电阻的阻值（如 330Ω）")
        if "单片机" in kws:
            out.append("补充晶振频率与复位电路要求")
        out.append("试试「查看帮助」了解全部能力")
    elif intent == "revise":
        out.append("把 C1 换成 100nF")
        out.append("增加一组 100nF 去耦电容")
        out.append("解释一下当前电路的工作原理")
    elif intent == "explain":
        out.append("生成一份完整的工作汇报")
        out.append("导出 KiCad 工程包")
    elif intent == "help":
        out.append("做一个 LED 闪烁最小系统")
        out.append("查看模板库")
    elif intent == "reset":
        out.append("做一个 5V 转 3.3V 的 LDO 稳压电路")
    return out[:4]


def analyze(text: str, has_design: bool = False) -> dict:
    """
    主入口：一句话 → 完整结构化理解。

    返回字段：
      intent        意图（含 label / confidence / matched）
      keywords      带类别与权重的关键词列表
      entities      元件编号、参数值、动作等实体
      template      最佳模板与候选打分
      summary       中文理解摘要
      suggestions   下一步建议
      needs_clarification / clarifying_question
      confidence    综合置信度
      normalized    归一化文本
    """
    text = raw_text(text)
    norm = _normalize(text)
    intent = classify_intent(text, has_design=has_design)
    keywords = recognize_keywords(text)
    entities = extract_entities(text)
    tpl_name, tpl_candidates = match_template(text)
    rich = len(keywords) >= 2 or bool(entities["values"])

    result = {
        "text": text,
        "normalized": norm,
        "intent": intent,
        "keywords": keywords,
        "entities": entities,
        "template": {"best": tpl_name, "candidates": tpl_candidates},
        "summary": "",
        "suggestions": [],
        "needs_clarification": False,
        "clarifying_question": "",
        "confidence": intent["confidence"],
    }
    result["summary"] = _describe(result)
    result["suggestions"] = _suggestions(result, has_design)

    # 信息不足时主动澄清（只对生成类意图）
    if intent["name"] == "generate" and (len(norm) < 8 or (not rich and len(norm) < 16)):
        result["needs_clarification"] = True
        result["clarifying_question"] = (
            "你的描述比较简短，我可以先按通用电路生成。想更准的话，补充一下"
            "「实现什么功能 + 供电电压 + 关键器件」，例如：做一个 5V 转 3.3V 的 LDO 稳压电路。"
        )
        result["confidence"] = round(min(result["confidence"], 0.6), 2)

    return result


def to_prompt_hint(analysis: dict) -> str:
    """把结构化理解注入 LLM Prompt，显著提升生成质量（消除歧义、锁定参数）"""
    lines = ["【需求结构化理解（由本地 NLU 预解析，请优先遵循）】"]
    lines.append("- 用户意图：" + analysis["intent"]["label"])
    kws = analysis["keywords"]
    if kws:
        grouped = {}
        for k in kws:
            grouped.setdefault(k["category"], []).append(k["term"])
        for cat, terms in grouped.items():
            lines.append(f"- 识别到的{cat}关键词：" + "、".join(terms))
    ents = analysis["entities"]
    for label, key in (("参数值", "values"), ("电压", "voltage"), ("频率", "frequency"),
                       ("元件编号", "refs"), ("接口网络", "nets")):
        if ents.get(key):
            lines.append(f"- {label}：" + "、".join(ents[key][:6]))
    lines.append("- 理解摘要：" + analysis["summary"])
    if analysis["clarifying_question"]:
        lines.append("- 注意：需求信息偏少，请采用最常见、最稳妥的工业实践补全细节。")
    lines.append("【根据以上理解输出电路设计 JSON，参数值必须与识别结果一致】")
    return "\n".join(lines)


def keyword_terms(analysis: dict) -> list[str]:
    """兼容旧接口：返回归一化关键词字符串列表"""
    return [k["term"] for k in analysis["keywords"]][:12]
