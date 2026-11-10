# -*- coding: utf-8 -*-
"""生成 EDA Agent 应用图标（assets/eda-agent.ico / .png）

只依赖 Pillow。想换配色或图案，改下面的常量后重跑即可：
    python scripts/make_icon.py
"""

from __future__ import annotations

import os

from PIL import Image, ImageDraw

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ASSETS = os.path.join(ROOT, "assets")

BG = "#0E7A46"          # PCB 绿
BG_LIGHT = "#16A163"    # 高光
FG = "#FFFFFF"          # 电路线
ACCENT = "#F0A05A"      # 橙色点缀
SIZE = 512


def rounded(draw, box, radius, fill=None, outline=None, width=1):
    draw.rounded_rectangle(box, radius=radius, fill=fill, outline=outline, width=width)


def build() -> Image.Image:
    img = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    # 底板：圆角矩形 + 顶部高光带
    rounded(d, (16, 16, 496, 496), 112, fill=BG)
    rounded(d, (16, 16, 496, 190), 112, fill=BG_LIGHT)
    d.rectangle((16, 150, 496, 190), fill=BG_LIGHT)  # 抹平高光带下缘的圆角

    # 中心芯片
    rounded(d, (166, 166, 346, 346), 26, fill=None, outline=FG, width=16)
    for cx, cy in ((214, 214), (298, 214), (214, 298), (298, 298)):
        d.ellipse((cx - 11, cy - 11, cx + 11, cy + 11), fill=FG)

    # 左侧引脚线
    for y in (214, 256, 298):
        d.line((56, y, 166, y), fill=FG, width=14)
        d.ellipse((42, y - 10, 62, y + 10), fill=FG)

    # 右侧引脚线 + 端点
    for y in (214, 256, 298):
        d.line((346, y, 456, y), fill=FG, width=14)
        d.ellipse((446, y - 12, 470, y + 12), fill=FG)

    # 顶部 / 底部走线
    d.line((256, 56, 256, 166), fill=FG, width=14)
    d.line((256, 346, 256, 456), fill=FG, width=14)
    d.ellipse((244, 44, 268, 68), fill=ACCENT)
    d.ellipse((244, 444, 268, 468), fill=ACCENT)

    return img


def main():
    os.makedirs(ASSETS, exist_ok=True)
    img = build()
    img.save(os.path.join(ASSETS, "eda-agent.png"))
    # 多尺寸 ICO：Windows 任务栏 / 快捷方式 / 安装包都会用到
    img.save(
        os.path.join(ASSETS, "eda-agent.ico"),
        format="ICO",
        sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)],
    )
    print("icon written to", ASSETS)


if __name__ == "__main__":
    main()
