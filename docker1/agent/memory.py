"""会话记忆：记录一次任务的完整轨迹（目标、步骤、指标、补丁）。"""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field


@dataclass
class Step:
    role: str          # "thought" | "action" | "observation" | "analysis" | "final"
    content: str
    ts: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {"role": self.role, "content": self.content, "ts": self.ts}


class Session:
    def __init__(self, goal: str):
        self.id = uuid.uuid4().hex[:12]
        self.goal = goal
        self.steps: list[Step] = []
        self.history: list[dict] = []   # 传给 LLM 的对话历史
        self.metrics_history: list[dict] = []
        self.patch_history: list[dict] = []
        self.trajectories: list[dict] = []  # 每次采样的完整飞行时序 {source, rows}
        self.created_at = time.time()

    def add(self, role: str, content: str):
        self.steps.append(Step(role, content))

    def add_metrics(self, metrics: dict):
        self.metrics_history.append(metrics)

    def add_patch(self, patch: dict):
        self.patch_history.append(patch)

    def add_trajectory(self, source: str, rows: list[dict]):
        """保存一次完整飞行时序（10Hz 原始采样），供 analyze_time_series 使用。"""
        if rows:
            self.trajectories.append({"source": source, "rows": rows})

    @property
    def last_trajectory(self) -> list[dict]:
        return self.trajectories[-1]["rows"] if self.trajectories else []

    def to_report(self) -> dict:
        return {
            "id": self.id,
            "goal": self.goal,
            "steps": [s.to_dict() for s in self.steps],
            "metrics_history": self.metrics_history,
            "patch_history": self.patch_history,
            "trajectory_count": len(self.trajectories),
        }
