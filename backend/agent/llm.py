# -*- coding: utf-8 -*-
"""LLM 客户端（OpenAI 兼容接口）"""

from __future__ import annotations

import json
import re

import httpx

from .. import config


class LLMError(Exception):
    pass


class LLMClient:
    """极简 OpenAI 兼容 chat.completions 客户端

    三级能力：
      1. 自定义 API key（DeepSeek/OpenAI/通义/Ollama 等）
      2. 免费在线 LLM（BlockRun 托管开源模型，无需 key，每个用户开箱即用）
      3. 均不可用时抛出 LLMError，由上层降级到离线模板
    """

    def __init__(self, api_key=None, base_url=None, model=None, timeout=None):
        # 读动态配置：前端「设置」面板可在不重启的情况下切换模型 / Key / 免费 LLM 开关
        s = config.llm_settings()
        self.api_key = api_key or s["api_key"]
        self.base_url = (base_url or s["base_url"]).rstrip("/")
        self.model = model or s["model"]
        self.timeout = timeout or s["timeout"]
        self.free_enabled = not s["no_free_llm"]
        self.free_base_url = s["free_base_url"]
        self.free_model = s["free_model"]

    @property
    def available(self) -> bool:
        return bool(self.api_key) or self.free_enabled

    @property
    def mode(self) -> str:
        """'custom'（自定义 key）/ 'free'（免费在线 LLM）/ 'none'"""
        if self.api_key:
            return "custom"
        if self.free_enabled:
            return "free"
        return "none"

    def chat(self, messages, temperature=0.2, json_mode=True, retries=2):
        """调用 chat.completions，返回文本内容。json_mode 时要求模型返回 JSON。"""
        if self.api_key:
            return self._chat_custom(messages, temperature, json_mode)
        if self.free_enabled:
            return self._chat_free(messages, temperature, json_mode, retries)
        raise LLMError("未配置 LLM（可在「设置」中填入 API Key，或开启免费在线 LLM）")

    def _chat_custom(self, messages, temperature, json_mode):
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "stream": False,
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        url = f"{self.base_url}/chat/completions"
        try:
            with httpx.Client(timeout=self.timeout) as client:
                resp = client.post(url, json=payload, headers=headers)
                resp.raise_for_status()
                data = resp.json()
        except httpx.HTTPStatusError as e:
            detail = e.response.text[:500]
            raise LLMError(f"LLM 请求失败 HTTP {e.response.status_code}: {detail}") from e
        except httpx.HTTPError as e:
            raise LLMError(f"LLM 网络错误: {e}") from e

        try:
            return data["choices"][0]["message"]["content"]
        except (KeyError, IndexError) as e:
            raise LLMError(f"LLM 响应格式异常: {data}") from e

    def _chat_free(self, messages, temperature, json_mode, retries):
        """免费在线 LLM（BlockRun，无需 key），带冷启动重试"""
        url = f"{self.free_base_url.rstrip('/')}/chat/completions"
        payload = {
            "model": self.free_model,
            "messages": messages,
            "temperature": temperature,
            "stream": False,
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        headers = {"Content-Type": "application/json"}  # 无需 Authorization

        last_err = None
        for attempt in range(retries + 1):
            try:
                with httpx.Client(timeout=self.timeout) as client:
                    resp = client.post(url, json=payload, headers=headers)
                    resp.raise_for_status()
                    data = resp.json()
                return data["choices"][0]["message"]["content"]
            except (httpx.HTTPError, KeyError, IndexError, ValueError) as e:
                # 免费模型冷启动 / 容量饱和 / 网络抖动，重试一次
                last_err = e
                continue
        raise LLMError(f"免费在线 LLM 请求失败（已重试 {retries} 次）: {last_err}")


def extract_json(text: str):
    """从模型输出中稳健提取 JSON 对象（兼容被 ```json 包裹的情况）"""
    if not text:
        raise LLMError("模型返回为空")
    # 去掉 markdown 代码块
    text = re.sub(r"```(?:json)?", "", text).strip()
    # 截取第一个 { 到最后一个 }
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise LLMError("模型输出中未找到 JSON 对象")
    try:
        return json.loads(text[start:end + 1])
    except json.JSONDecodeError as e:
        raise LLMError(f"JSON 解析失败: {e}") from e
