# -*- coding: utf-8 -*-
"""全局配置：环境变量 + 默认值"""

import os
import sys


def _is_frozen():
    """PyInstaller 打包后运行"""
    return getattr(sys, "frozen", False)


if _is_frozen():
    # 打包后：资源在 _MEIPASS 临时目录，输出目录放到用户主目录下
    BUNDLE_DIR = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    BASE_DIR = BUNDLE_DIR
    TEMPLATE_DIR = os.path.join(BUNDLE_DIR, "backend", "templates")
    FRONTEND_DIR = os.path.join(BUNDLE_DIR, "frontend")
    DEFAULT_OUTPUT = os.path.join(os.path.expanduser("~"), "eda-agent-output")
else:
    BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    TEMPLATE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "templates")
    FRONTEND_DIR = os.path.join(BASE_DIR, "frontend")
    DEFAULT_OUTPUT = os.path.join(BASE_DIR, "output")

# 输出目录（生成的项目文件、报告放这里）
OUTPUT_DIR = os.environ.get("EDA_AGENT_OUTPUT", DEFAULT_OUTPUT)

# ---------------------------------------------------------------------------
# LLM 配置（OpenAI 兼容接口）
# 支持 OpenAI / DeepSeek / 通义千问 / Ollama 等任意 OpenAI 兼容服务
# ---------------------------------------------------------------------------
LLM_API_KEY = os.environ.get("EDA_AGENT_API_KEY", "") or os.environ.get("OPENAI_API_KEY", "")
LLM_BASE_URL = os.environ.get("EDA_AGENT_BASE_URL", "") or os.environ.get("OPENAI_BASE_URL", "https://api.deepseek.com/v1")
LLM_MODEL = os.environ.get("EDA_AGENT_MODEL", "") or os.environ.get("OPENAI_MODEL", "deepseek-chat")
LLM_TIMEOUT = float(os.environ.get("EDA_AGENT_TIMEOUT", "60"))

# ---------------------------------------------------------------------------
# 免费在线 LLM（无需 API key）
# BlockRun 托管开源模型（NVIDIA 免费推理），OpenAI 兼容，无需注册/无需 key。
# 每个用户开箱即用；不稳定的网络环境下会自动降级到离线模板。
# 设 EDA_AGENT_NO_FREE_LLM=1 可关闭（例如内网无法访问海外服务时）。
# ---------------------------------------------------------------------------
FREE_LLM_BASE_URL = os.environ.get("EDA_AGENT_FREE_LLM_BASE_URL", "https://blockrun.ai/api/v1")
FREE_LLM_MODEL = os.environ.get("EDA_AGENT_FREE_LLM_MODEL", "nvidia/gpt-oss-120b")
FREE_LLM_ENABLED = os.environ.get("EDA_AGENT_NO_FREE_LLM", "") != "1"

# KiCad 可执行文件（留空则自动探测，未安装时跳过 ERC/DRC）
KICAD_CLI = os.environ.get("KICAD_CLI", "")


def has_llm() -> bool:
    """是否可用真实 LLM（自定义 key 或免费在线 LLM）"""
    return bool(LLM_API_KEY) or FREE_LLM_ENABLED
