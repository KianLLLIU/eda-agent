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
    """极简 OpenAI 兼容 chat.completions 客户端"""

    def __init__(self, api_key=None, base_url=None, model=None, timeout=None):
        self.api_key = api_key or config.LLM_API_KEY
        self.base_url = (base_url or config.LLM_BASE_URL).rstrip("/")
        self.model = model or config.LLM_MODEL
        self.timeout = timeout or config.LLM_TIMEOUT

    @property
    def available(self) -> bool:
        return bool(self.api_key)

    def chat(self, messages, temperature=0.2, json_mode=True):
        """调用 chat.completions，返回文本内容。json_mode 时要求模型返回 JSON。"""
        if not self.available:
            raise LLMError("未配置 LLM API Key，请设置环境变量 EDA_AGENT_API_KEY")

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
