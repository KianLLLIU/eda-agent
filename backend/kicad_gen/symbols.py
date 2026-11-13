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
# v2.1 新增：通用矩形 IC 符号（数据驱动，加器件只需给一张引脚表）
# ---------------------------------------------------------------------------
def _ic(left, right, half_w=7.62, pitch=2.54):
    """双列矩形 IC 符号。

    left  : [(pin, name, etype), ...] 自上而下
    right : [(pin, name, etype), ...] 自下而上（与真实 DIP 引脚顺序一致）
    """
    n = max(len(left), len(right), 1)
    half_h = ((n - 1) * pitch) / 2.0
    pins = []
    for i, (num, name, etype) in enumerate(left):
        pins.append(_pin(num, name, etype, -half_w, half_h - i * pitch, 0))
    for i, (num, name, etype) in enumerate(right):
        pins.append(_pin(num, name, etype, half_w, -half_h + i * pitch, 180))
    return {"pins": pins, "graphics": [_rect(-half_w, -half_h, half_w, half_h)]}


def _module(pins, half_w=7.62, pitch=2.54):
    """单列「模块/传感器」符号：引脚全部在左侧，名字显示在框内。

    pins: [(pin, name, etype), ...] 自上而下
    """
    n = max(len(pins), 1)
    half_h = ((n - 1) * pitch) / 2.0
    out = [_pin(num, name, etype, -half_w, half_h - i * pitch, 0)
           for i, (num, name, etype) in enumerate(pins)]
    return {"pins": out, "graphics": [_rect(-half_w, -half_h, half_w, half_h)]}


def _potentiometer():
    """三端电位器：1 端、2 抽头、3 端（横放，抽头朝上）"""
    return {
        "pins": [
            _pin(1, "1", PASSIVE, -5.08, 0, 0),
            _pin(2, "W", PASSIVE, 0, 2.54, 90),
            _pin(3, "3", PASSIVE, 5.08, 0, 180),
        ],
        "graphics": [
            _rect(-2.54, -1.27, 2.54, 1.27),
            # 抽头箭头
            ("line", [(0, 1.27), (0, 0.0)]),
            ("line", [(-0.635, 0.635), (0, 0.0), (0.635, 0.635)]),
        ],
    }


def _buzzer():
    """有源蜂鸣器（2 引脚）"""
    return {
        "pins": [
            _pin(1, "+", PASSIVE, -5.08, 0, 0),
            _pin(2, "-", PASSIVE, 5.08, 0, 180),
        ],
        "graphics": [
            _rect(-2.54, -2.54, 2.54, 2.54),
            ("line", [(-1.27, 1.27), (1.27, 1.27)]),
            ("line", [(-1.27, -1.27), (1.27, -1.27)]),
        ],
    }


def _speaker():
    """扬声器（2 引脚）"""
    return {
        "pins": [
            _pin(1, "1", PASSIVE, -5.08, 0, 0),
            _pin(2, "2", PASSIVE, 5.08, 0, 180),
        ],
        "graphics": [
            _rect(-2.54, -2.54, -0.635, 2.54),
            ("line", [(-0.635, 1.905), (1.905, 2.54), (1.905, -2.54), (-0.635, -1.905)]),
        ],
    }


def _battery_cell():
    """单节电池 / 电池座（2 引脚，带正负极标记）"""
    return {
        "pins": [
            _pin(1, "+", PASSIVE, -5.08, 0, 0),
            _pin(2, "-", PASSIVE, 5.08, 0, 180),
        ],
        "graphics": [
            ("line", [(-1.27, -2.54), (-1.27, 2.54)]),
            ("line", [(0.508, -1.27), (0.508, 1.27)]),
            ("line", [(-3.81, 2.54), (-1.27, 2.54)]),
            ("line", [(-3.81, 2.54), (-3.81, 1.27)]),
            ("line", [(-4.445, 1.905), (-3.175, 1.905)]),
        ],
    }


def _ldr():
    """光敏电阻（2 引脚）"""
    return {
        "pins": [
            _pin(1, "1", PASSIVE, -5.08, 0, 0),
            _pin(2, "2", PASSIVE, 5.08, 0, 180),
        ],
        "graphics": [
            _rect(-2.54, -1.27, 2.54, 1.27),
            # 入射光箭头
            ("line", [(-1.905, 2.54), (-0.635, 1.524)]),
            ("line", [(-1.905, 2.54), (-1.651, 1.778)]),
            ("line", [(-0.635, 2.54), (0.635, 1.524)]),
            ("line", [(-0.635, 2.54), (-0.381, 1.778)]),
        ],
    }


def _push_button():
    """轻触按键（2 引脚常开）"""
    return {
        "pins": [
            _pin(1, "1", PASSIVE, -5.08, 0, 0),
            _pin(2, "2", PASSIVE, 5.08, 0, 180),
        ],
        "graphics": [
            ("line", [(-5.08, 0), (-1.905, 0)]),
            ("line", [(1.905, 0), (5.08, 0)]),
            ("line", [(-1.905, 0), (-1.905, 1.27)]),
            ("line", [(1.905, 0), (1.905, 1.27)]),
            ("line", [(-1.905, 1.27), (1.905, 1.27)]),
            ("line", [(0, 1.27), (0, 2.54)]),
            ("line", [(-0.635, 2.54), (0.635, 2.54)]),
        ],
    }


def _nmos():
    """N 沟道 MOSFET：1=G, 2=S, 3=D（SOT-23 常见排布）"""
    return {
        "pins": [
            _pin(1, "G", INPUT, -5.08, 0, 0),
            _pin(2, "S", PASSIVE, 0, -5.08, 270),
            _pin(3, "D", PASSIVE, 0, 5.08, 90),
        ],
        "graphics": [
            ("line", [(-5.08, 0), (-2.54, 0)]),
            ("line", [(-2.54, -2.54), (-2.54, 2.54)]),
            ("line", [(-1.905, -2.54), (-1.905, -0.635)]),
            ("line", [(-1.905, -0.635), (-1.905, 0.635)]),
            ("line", [(-1.905, 0.635), (-1.905, 2.54)]),
            ("line", [(0, 5.08), (0, 1.905), (-1.905, 1.905)]),
            ("line", [(0, -5.08), (0, -1.905), (-1.905, -1.905)]),
            ("line", [(0, 0), (-1.905, 0)]),
            ("line", [(0, 0), (0, 0.635), (0.635, 0.381)]),
            ("line", [(-2.54, 0), (-1.905, 0)]),
        ],
    }


# ---- 经典集成电路 ---------------------------------------------------------
def _ne555():
    return _ic(
        [("1", "GND", POWER_IN), ("2", "TRIG", INPUT),
         ("3", "OUT", OUTPUT), ("4", "RESET", INPUT)],
        [("5", "CV", INPUT), ("6", "THR", INPUT),
         ("7", "DISCH", PASSIVE), ("8", "VCC", POWER_IN)],
    )


def _cd4017():
    return _ic(
        [("1", "Q5", OUTPUT), ("2", "Q1", OUTPUT), ("3", "Q0", OUTPUT),
         ("4", "Q2", OUTPUT), ("5", "Q6", OUTPUT), ("6", "Q7", OUTPUT),
         ("7", "Q4", OUTPUT), ("8", "VSS", POWER_IN)],
        [("9", "Q8", OUTPUT), ("10", "Q9", OUTPUT), ("11", "Q3", OUTPUT),
         ("12", "CO", OUTPUT), ("13", "CLK_INH", INPUT), ("14", "CLK", INPUT),
         ("15", "RESET", INPUT), ("16", "VDD", POWER_IN)],
    )


def _lm393():
    return _ic(
        [("1", "OUT1", OUTPUT), ("2", "IN1-", INPUT),
         ("3", "IN1+", INPUT), ("4", "GND", POWER_IN)],
        [("5", "IN2+", INPUT), ("6", "IN2-", INPUT),
         ("7", "OUT2", OUTPUT), ("8", "VCC", POWER_IN)],
    )


def _lm386():
    return _ic(
        [("1", "GAIN", PASSIVE), ("2", "IN-", INPUT),
         ("3", "IN+", INPUT), ("4", "GND", POWER_IN)],
        [("5", "VOUT", OUTPUT), ("6", "VS", POWER_IN),
         ("7", "BYPASS", PASSIVE), ("8", "GAIN", PASSIVE)],
    )


def _max485():
    return _ic(
        [("1", "RO", OUTPUT), ("2", "RE", INPUT),
         ("3", "DE", INPUT), ("4", "DI", INPUT)],
        [("5", "GND", POWER_IN), ("6", "A", BIDI),
         ("7", "B", BIDI), ("8", "VCC", POWER_IN)],
    )


def _tp4056():
    return _ic(
        [("1", "TEMP", INPUT), ("2", "PROG", PASSIVE),
         ("3", "GND", POWER_IN), ("4", "VCC", POWER_IN)],
        [("5", "BAT", POWER_OUT), ("6", "STDBY", OUTPUT),
         ("7", "CHRG", OUTPUT), ("8", "CE", INPUT)],
    )


def _uln2003():
    return _ic(
        [("1", "IN1", INPUT), ("2", "IN2", INPUT), ("3", "IN3", INPUT),
         ("4", "IN4", INPUT), ("5", "IN5", INPUT), ("6", "IN6", INPUT),
         ("7", "IN7", INPUT), ("8", "GND", POWER_IN)],
        [("9", "COM", PASSIVE), ("10", "OUT7", OUTPUT), ("11", "OUT6", OUTPUT),
         ("12", "OUT5", OUTPUT), ("13", "OUT4", OUTPUT), ("14", "OUT3", OUTPUT),
         ("15", "OUT2", OUTPUT), ("16", "OUT1", OUTPUT)],
    )


def _lm2596():
    """LM2596S-5 降压开关稳压（TO-220-5）"""
    return _ic(
        [("1", "VIN", POWER_IN), ("2", "OUT", POWER_OUT), ("3", "GND", POWER_IN)],
        [("4", "FB", INPUT), ("5", "ON/OFF", INPUT)],
    )


def _relay():
    """SRD 系列 5V 继电器（1、2 线圈，3 COM，4 NO，5 NC）"""
    return _ic(
        [("1", "COIL+", PASSIVE), ("2", "COIL-", PASSIVE)],
        [("3", "COM", PASSIVE), ("4", "NO", PASSIVE), ("5", "NC", PASSIVE)],
        half_w=6.35,
    )


# ---- 模块 / 传感器转接板 ---------------------------------------------------
def _dht11():
    return _module([("1", "VDD", POWER_IN), ("2", "DATA", BIDI), ("3", "GND", POWER_IN)])


def _ds18b20():
    return _module([("1", "GND", POWER_IN), ("2", "DQ", BIDI), ("3", "VDD", POWER_IN)])


def _hcsr04():
    return _module([("1", "VCC", POWER_IN), ("2", "TRIG", INPUT),
                    ("3", "ECHO", OUTPUT), ("4", "GND", POWER_IN)])


def _mq2():
    return _module([("1", "VCC", POWER_IN), ("2", "GND", POWER_IN),
                    ("3", "DO", OUTPUT), ("4", "AO", OUTPUT)])


def _hc_sr501():
    return _module([("1", "VCC", POWER_IN), ("2", "OUT", OUTPUT), ("3", "GND", POWER_IN)])


def _ssd1306():
    return _module([("1", "GND", POWER_IN), ("2", "VCC", POWER_IN),
                    ("3", "SCL", INPUT), ("4", "SDA", BIDI)])


def _sd_card():
    return _module([("1", "3V3", POWER_IN), ("2", "CS", OUTPUT), ("3", "MOSI", OUTPUT),
                    ("4", "CLK", OUTPUT), ("5", "MISO", INPUT), ("6", "GND", POWER_IN)])


def _esp01():
    """ESP-01 / ESP-01S 2x4 排针模块"""
    return _ic(
        [("1", "TXD", OUTPUT), ("2", "CH_PD", INPUT),
         ("3", "RST", INPUT), ("4", "VCC", POWER_IN)],
        [("5", "GND", POWER_IN), ("6", "GPIO2", BIDI),
         ("7", "GPIO0", BIDI), ("8", "RXD", INPUT)],
    )


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
    # v2.1 扩充：无源与分立器件
    "Device:R_Potentiometer": _potentiometer(),
    "Device:Buzzer": _buzzer(),
    "Device:Speaker": _speaker(),
    "Device:Battery_Cell": _battery_cell(),
    "Device:R_PHOTO": _ldr(),
    "Device:SW_Push": _push_button(),
    "Device:Q_NMOS_GSD": _nmos(),
    "Relay:SANYOU_SRD_05VDC": _relay(),
    # v2.1 扩充：经典集成电路
    "Timer:NE555P": _ne555(),
    "Logic_4xxx:CD4017": _cd4017(),
    "Comparator:LM393": _lm393(),
    "Amplifier_Audio:LM386": _lm386(),
    "Interface_UART:MAX485": _max485(),
    "Battery_Management:TP4056": _tp4056(),
    "Transistor_Array:ULN2003": _uln2003(),
    "Regulator_Linear:LM7805": _ldo(),
    "Regulator_Switching:LM2596S-5": _lm2596(),
    # v2.1 扩充：模块 / 传感器转接板
    "Sensor:DHT11": _dht11(),
    "Sensor:DS18B20": _ds18b20(),
    "Sensor:HC-SR04": _hcsr04(),
    "Sensor:MQ-2": _mq2(),
    "Sensor:HC-SR501": _hc_sr501(),
    "Module:SSD1306": _ssd1306(),
    "Module:SD_Card": _sd_card(),
    "Module:ESP-01": _esp01(),
}

# 动态注册 1x2 ~ 1x12 排针
for _n in range(2, 13):
    SYMBOL_LIB[f"Connector_Generic:Conn_01x{_n:02d}"] = _pin_header(_n)

# 2x4 排针（ESP-01 类模块常用）
SYMBOL_LIB["Connector_Generic:Conn_02x04_Odd_Even"] = _esp01()


def get_symbol(lib_id):
    """按 lib_id 取符号定义；不存在则返回 None"""
    return SYMBOL_LIB.get(lib_id)
