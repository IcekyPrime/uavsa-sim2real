"""LLM 客户端：OpenAI 兼容协议（默认 DeepSeek）。

只依赖 httpx，无第三方 SDK，便于在 Docker / 本地统一运行。
"""
from __future__ import annotations

import json
import re

import httpx

from .config import config


class LLMClient:
    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
        temperature: float | None = None,
    ):
        self.api_key = api_key or config.llm_api_key
        self.base_url = (base_url or config.llm_base_url).rstrip("/")
        self.model = model or config.llm_model
        self.temperature = temperature if temperature is not None else config.llm_temperature

    def chat_full(self, messages: list[dict], temperature: float | None = None) -> tuple[str, str]:
        """调用 chat/completions，返回 (reasoning_content, content)。

        适配 reasoning 模型（如 deepseek-v4-pro）：思考在 reasoning_content，
        最终输出在 content。普通模型则 reasoning_content 为空字符串。
        """
        if not self.api_key:
            raise RuntimeError("缺少 LLM_API_KEY，请在 .env 或 GUI 设置中配置")
        url = f"{self.base_url}/chat/completions"
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature if temperature is not None else self.temperature,
        }
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        with httpx.Client(timeout=120) as client:
            resp = client.post(url, json=payload, headers=headers)
        resp.raise_for_status()
        data = resp.json()
        msg = data["choices"][0]["message"]
        return msg.get("reasoning_content") or "", msg.get("content") or ""

    def chat(self, messages: list[dict], temperature: float | None = None) -> str:
        """调用 chat/completions，返回 assistant 文本（content）。"""
        _, content = self.chat_full(messages, temperature)
        return content

    # ---- 结构化输出辅助：让模型返回 JSON 动作 ----
    @staticmethod
    def extract_json(text: str) -> dict | None:
        """从模型输出中抽取 JSON 对象（容忍 ```json 代码块与前后说明文字）。"""
        text = text.strip()
        fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.S)
        if fence:
            text = fence.group(1)
        # 取第一个 { 到最后一个 } 之间
        start, end = text.find("{"), text.rfind("}")
        if start == -1 or end == -1 or end <= start:
            return None
        candidate = text[start : end + 1]
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            return None


llm = LLMClient()
