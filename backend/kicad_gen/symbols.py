# -*- coding: utf-8 -*-
"""
KiCad 符号库定义（自研，数据驱动）

每个符号由「引脚列表」和「图形」两部分组成，用于在原理图中生成内嵌的
lib_symbols 定义。符号采用「水平横放」约定（2 引脚器件 pin1 在左、pin2 在右），
这样放置时无需旋转，引脚坐标计算最简单、最不容易出错。

引脚元组格式： (number, name, etype, px, py, angle, length)
  - px/py  : 引脚电气点在符号局部坐标系中的位置（单位 mm）
  - angle  : 引脚朝向，0=向右，90=向上，180=向左，270=向下
  - etype  : electrical type（passive/input/output/power_in/power_out/bidirectional 等）
"""

# 常用电气类型
PASSIVE = "passive"
INPUT = "input"
OUTPUT = "output"
BIDI = "bidirectional"
POWER_IN = "power_in"
POWER_OUT = "power_out"


def _pin(num, name, etype, px, py, angle=0, length=2.54):
    return (str(num), name, etype, float(px), float(py), int(angle), float(length))


# 图形原语： ("rect", x1, y1, x2, y2)  或  ("line", [(x1,y1),(x2,y2),...])
def _rect(x1, y1, x2, y2):
    return ("rect", x1, y1, x2, y2)


def _line(points):
    return ("line", points)


# ---------------------------------------------------------------------------
# 无源器件（水平横放：pin1 左、pin2 右）
# ---------------------------------------------------------------------------
def _resistor():
    return {
        "pins": [
            _pin(1, "1", PASSIVE, -2.54, 0, 0),
            _pin(2, "2", PASSIVE, 2.54, 0, 180),
        ],
        "graphics": [
            _rect(-1.27, -1.27, 1.27, 1.27),
        ],
    }


def _capacitor():
    return {
        "pins": [
            _pin(1, "1", PASSIVE, -2.54, 0, 0),
            _pin(2, "2", PASSIVE, 2.54, 0, 180),
        ],
        "graphics": [
            # 两片平行板
            ("line", [(-0.762, -1.27), (-0.762, 1.27)]),
            ("line", [(0.762, -1.27), (0.762, 1.27)]),
        ],
    }


def _polarized_capacitor():
    return {
        "pins": [
            _pin(1, "1", PASSIVE, -2.54, 0, 0),
            _pin(2, "2", PASSIVE, 2.54, 0, 180),
        ],
        "graphics": [
            ("line", [(-1.016, -1.27), (-1.016, 1.27)]),   # 负极（直板）
            ("line", [(-0.2, -1.27), (-0.2, 1.27)]),
            ("line", [(-0.2, -1.27), (-1.016, -1.27)]),
            ("line", [(-0.2, 1.27), (-1.016, 1.27)]),
            ("line", [(0.762, -1.27), (0.762, 1.27)]),      # 正极（弯板）
            ("line", [(0.762, -1.27), (1.016, -1.016)]),
            ("line", [(0.762, 1.27), (1.016, 1.016)]),
        ],
    }


def _inductor():
    return {
        "pins": [
            _pin(1, "1", PASSIVE, -2.54, 0, 0),
            _pin(2, "2", PASSIVE, 2.54, 0, 180),
        ],
        "graphics": [
            ("line", [(-1.27, 0), (-0.762, 0), (-0.762, -1.016), (-0.254, -1.016),
                      (-0.254, 1.016), (0.254, 1.016), (0.254, -1.016),
                      (0.762, -1.016), (0.762, 0), (1.27, 0)]),
        ],
    }


def _led():
    return {
        "pins": [
            _pin(1, "K", PASSIVE, -2.54, 0, 0),
            _pin(2, "A", PASSIVE, 2.54, 0, 180),
        ],
        "graphics": [
            # 三角形 + 横线
            ("line", [(-1.27, 1.27), (1.27, 0), (-1.27, -1.27), (-1.27, 1.27)]),
            ("line", [(1.27, 1.27), (1.27, -1.27)]),
            # 箭头（发光指示）
            ("line", [(0.254, 0.762), (0.254, 1.524)]),
            ("line", [(0.254, -0.762), (0.254, -1.524)]),
            ("line", [(0.254, 1.524), (1.016, 1.016)]),
            ("line", [(0.254, 1.524), (-0.508, 1.016)]),
        ],
    }


def _diode():
    return {
        "pins": [
            _pin(1, "K", PASSIVE, -2.54, 0, 0),
            _pin(2, "A", PASSIVE, 2.54, 0, 180),
        ],
        "graphics": [
            ("line", [(-1.27, 1.27), (1.27, 0), (-1.27, -1.27), (-1.27, 1.27)]),
            ("line", [(1.27, 1.27), (1.27, -1.27)]),
        ],
    }


def _crystal():
    return {
        "pins": [
            _pin(1, "1", PASSIVE, -2.54, 0, 0),
            _pin(2, "2", PASSIVE, 2.54, 0, 180),
        ],
        "graphics": [
            _rect(-1.016, -1.524, 1.016, 1.524),
            # 两侧接地板
            ("line", [(-2.54, -1.016), (-2.54, 1.016)]),
            ("line", [(2.54, -1.016), (2.54, 1.016)]),
        ],
    }


# ---------------------------------------------------------------------------
# 三端器件
# ---------------------------------------------------------------------------
def _ldo():
    """通用三端线性稳压器：1=IN, 2=GND, 3=OUT"""
    return {
        "pins": [
            _pin(1, "IN", POWER_IN, -2.54, 1.27, 0),
            _pin(2, "GND", POWER_IN, 0, -2.54, 270),
            _pin(3, "OUT", POWER_OUT, 2.54, 1.27, 180),
        ],
        "graphics": [
            _rect(-2.54, -1.27, 2.54, 2.54),
        ],
    }


def _npn_transistor():
    """NPN 三极管：1=C, 2=B, 3=E"""
    return {
        "pins": [
            _pin(1, "C", PASSIVE, 0, 2.54, 90),
            _pin(2, "B", INPUT, -2.54, -1.27, 0),
            _pin(3, "E", PASSIVE, 0, -2.54, 270),
        ],
        "graphics": [
            ("line", [(0, 2.54), (0, 0.508)]),
            ("line", [(0, -0.508), (0, -2.54)]),
            ("line", [(-1.27, 0.508), (1.27, 0.508)]),
            ("line", [(-0.508, 0.508), (0, 0.508), (0.508, 0.508)]),
            ("line", [(0, 0.508), (-1.27, 1.27)]),
            ("line", [(0, 0.508), (-1.27, -1.27)]),
            ("line", [(-2.54, -1.27), (0, -0.508)]),
        ],
    }


# ---------------------------------------------------------------------------
# 接插件（排针）
# ---------------------------------------------------------------------------
def _pin_header(n):
    """1xN 排针：引脚 1 在顶部"""
    pins = []
    half = (n - 1) * 2.54 / 2.0
    for i in range(n):
        y = half - i * 2.54
        pins.append(_pin(i + 1, str(i + 1), PASSIVE, -2.54, y, 0))
    graphics = [_rect(-1.27, -half - 1.27, 1.27, half + 1.27)]
    return {"pins": pins, "graphics": graphics}


# ---------------------------------------------------------------------------
# MCU：ATmega328P（DIP-28）
# ---------------------------------------------------------------------------
_ATMEGA328P_PINS = [
    # (pin_number, name, etype)
    (1, "PC6/RESET", INPUT),
    (2, "PD0/RXD", BIDI),
    (3, "PD1/TXD", BIDI),
    (4, "PD2/INT0", BIDI),
    (5, "PD3/INT1", BIDI),
    (6, "PD4", BIDI),
    (7, "VCC", POWER_IN),
    (8, "GND", POWER_IN),
    (9, "PB6/XTAL1", INPUT),
    (10, "PB7/XTAL2", INPUT),
    (11, "PD5", BIDI),
    (12, "PD6", BIDI),
    (13, "PD7", BIDI),
    (14, "PB0", BIDI),
    (15, "PB1", BIDI),
    (16, "PB2", BIDI),
    (17, "PB3/MOSI", BIDI),
    (18, "PB4/MISO", BIDI),
    (19, "PB5/SCK", BIDI),
    (20, "AVCC", POWER_IN),
    (21, "AREF", INPUT),
    (22, "GND", POWER_IN),
    (23, "PC0/ADC0", BIDI),
    (24, "PC1/ADC1", BIDI),
    (25, "PC2/ADC2", BIDI),
    (26, "PC3/ADC3", BIDI),
    (27, "PC4/ADC4", BIDI),
    (28, "PC5/ADC5", BIDI),
]


def _atmega328p():
    pins = []
    n = len(_ATMEGA328P_PINS)
    half = (n - 1) * 2.54 / 2.0
    for i, (num, name, etype) in enumerate(_ATMEGA328P_PINS):
        if num <= 14:  # 左侧，从上到下
            y = half - (num - 1) * 2.54
            pins.append(_pin(num, name, etype, -7.62, y, 0))
        else:          # 右侧，从下到上
            y = -half + (num - 15) * 2.54
            pins.append(_pin(num, name, etype, 7.62, y, 180))
    graphics = [_rect(-7.62, -half, 7.62, half)]
    return {"pins": pins, "graphics": graphics}


# ---------------------------------------------------------------------------
# 符号注册表： 键 = "库名:符号名"
# ---------------------------------------------------------------------------
SYMBOL_LIB = {
    "Device:R": _resistor(),
    "Device:C": _capacitor(),
    "Device:CP": _polarized_capacitor(),
    "Device:L": _inductor(),
    "Device:LED": _led(),
    "Device:D": _diode(),
    "Device:Crystal": _crystal(),
    "Device:Q_NPN_BCE": _npn_transistor(),
    "Regulator_Linear:LDO": _ldo(),
    "MCU_Microchip_ATmega:ATmega328P": _atmega328p(),
}

# 动态注册 1x2 ~ 1x12 排针
for _n in range(2, 13):
    SYMBOL_LIB[f"Connector_Generic:Conn_01x{_n:02d}"] = _pin_header(_n)


def get_symbol(lib_id):
    """按 lib_id 取符号定义；不存在则返回 None"""
    return SYMBOL_LIB.get(lib_id)
