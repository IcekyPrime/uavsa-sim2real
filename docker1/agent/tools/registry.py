"""工具抽象与注册表。"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Callable


@dataclass
class Tool:
    name: str
    description: str
    parameters: dict  # {"param": {"type": ..., "description": ..., "required": bool}}
    func: Callable[[dict], dict]
    tags: list[str] = field(default_factory=list)

    def to_spec(self) -> str:
        """生成给 LLM 的可读说明。"""
        lines = [f"- {self.name}: {self.description}"]
        for pname, meta in self.parameters.items():
            req = "必填" if meta.get("required") else "可选"
            lines.append(f"    参数 {pname} ({meta.get('type', 'string')}, {req}): {meta.get('description', '')}")
        return "\n".join(lines)

    def __call__(self, args: dict) -> dict:
        try:
            return self.func(args or {})
        except Exception as e:  # 工具异常以结构化方式回传，不中断循环
            return {"error": f"{type(e).__name__}: {e}"}


class ToolRegistry:
    def __init__(self):
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool):
        self._tools[tool.name] = tool

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def names(self) -> list[str]:
        return list(self._tools.keys())

    def spec_text(self) -> str:
        return "\n".join(t.to_spec() for t in self._tools.values())

    def execute(self, name: str, args: dict) -> dict:
        tool = self._tools.get(name)
        if not tool:
            return {"error": f"未知工具 {name}；可用工具：{', '.join(self.names())}"}
        return tool(args)


def safe_json(obj) -> str:
    """把任意结果安全序列化，供 LLM 阅读。"""
    try:
        return json.dumps(obj, ensure_ascii=False, indent=2, default=str)
    except Exception:
        return str(obj)
