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

# 用户数据目录：会话历史、设置、桌面端日志
# 无论源码运行还是打包运行，都落在用户主目录，保证可写且卸载后可清理
USER_DATA_DIR = os.environ.get("EDA_AGENT_DATA", os.path.join(os.path.expanduser("~"), ".eda-agent"))

APP_NAME = "EDA Agent"
APP_VERSION = "2.0.0"
IS_FROZEN = _is_frozen()

# ---------------------------------------------------------------------------
# 运行时设置（前端「设置」面板写入，仅当前进程有效，不写入环境变量）
# ---------------------------------------------------------------------------
RUNTIME: dict = {}
_SETTINGS_FILE = os.path.join(USER_DATA_DIR, "settings.json")
# 允许持久化到磁盘的非敏感项；API Key 只保留在内存中，不落盘
PERSISTENT_KEYS = ("base_url", "model", "no_free_llm", "timeout", "auto_preview", "theme")


def _load_settings():
    try:
        if os.path.isfile(_SETTINGS_FILE):
            import json
            with open(_SETTINGS_FILE, "r", encoding="utf-8") as f:
                saved = json.load(f)
            for k in PERSISTENT_KEYS:
                if k in saved:
                    RUNTIME[k] = saved[k]
    except Exception:
        pass


def apply_settings(data: dict) -> dict:
    """应用前端设置，返回当前生效配置（脱敏）"""
    for key in ("api_key", "base_url", "model", "timeout", "no_free_llm", "auto_preview", "theme"):
        if key in data and data[key] is not None:
            RUNTIME[key] = data[key]
    try:
        import json
        os.makedirs(USER_DATA_DIR, exist_ok=True)
        with open(_SETTINGS_FILE, "w", encoding="utf-8") as f:
            json.dump({k: RUNTIME[k] for k in PERSISTENT_KEYS if k in RUNTIME}, f, ensure_ascii=False, indent=2)
    except Exception:
        pass
    return public_settings()


def public_settings() -> dict:
    """返回给前端的配置（API Key 脱敏）"""
    s = llm_settings()
    return {
        "api_key_set": bool(s["api_key"]),
        "base_url": s["base_url"],
        "model": s["model"],
        "timeout": s["timeout"],
        "no_free_llm": s["no_free_llm"],
        "free_llm_model": FREE_LLM_MODEL,
        "auto_preview": RUNTIME.get("auto_preview", True),
        "theme": RUNTIME.get("theme", "light"),
        "output_dir": OUTPUT_DIR,
        "data_dir": USER_DATA_DIR,
        "frozen": IS_FROZEN,
        "version": APP_VERSION,
    }


def llm_settings() -> dict:
    """动态 LLM 配置：运行时设置 > 环境变量 > 默认值"""
    return {
        "api_key": RUNTIME.get("api_key", LLM_API_KEY),
        "base_url": RUNTIME.get("base_url", LLM_BASE_URL),
        "model": RUNTIME.get("model", LLM_MODEL),
        "timeout": float(RUNTIME.get("timeout", LLM_TIMEOUT)),
        "no_free_llm": bool(RUNTIME.get("no_free_llm", not FREE_LLM_ENABLED)),
        "free_base_url": FREE_LLM_BASE_URL,
        "free_model": FREE_LLM_MODEL,
    }


_load_settings()

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
