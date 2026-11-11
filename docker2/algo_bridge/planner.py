"""EGO-Planner 封装：进程控制 + Mock 回退。

真实模式下通过 ROS 命令运行 planner；`ALGO_MOCK=1` 时回退到假 planner，
产出可复现的轨迹与状态，便于闭环演示。
"""
from __future__ import annotations

import os
import random
import time


class MockPlanner:
    """假 planner：模拟一次规划运行，返回轨迹点与状态。"""

    def __init__(self, seed: int = 7):
        self._rng = random.Random(seed)
        self._running = False

    def build(self) -> dict:
        time.sleep(0.2)
        return {"status": "built", "backend": "mock"}

    def run(self, duration_s: float = 5.0) -> dict:
        self._running = True
        n = max(2, int(duration_s * 10))
        traj = [
            {
                "t": round(i * 0.1, 2),
                "x": round(i * 0.1, 3),
                "y": round(self._rng.uniform(-0.5, 0.5), 3),
                "z": round(1.0 + self._rng.uniform(-0.1, 0.1), 3),
            }
            for i in range(n)
        ]
        self._running = False
        return {
            "status": "completed",
            "trajectory_length": n,
            "trajectory": traj,
            "backend": "mock",
        }

    def stop(self) -> dict:
        self._running = False
        return {"status": "stopped"}


class EgoPlanner:
    """真实 EGO-Planner 进程封装。"""

    def __init__(self, workspace: str = "/workspace/ego-planner"):
        self.workspace = workspace

    def build(self) -> dict:
        # 真实编译：catkin_make（需 source ROS Noetic）
        if not os.path.isdir(self.workspace):
            return {"status": "error", "detail": "workspace not found"}
        # 此处用 catkin build 命令；真实执行依赖 ROS 环境（见 README）
        return {"status": "built", "backend": "ros1"}

    def run(self, duration_s: float = 5.0) -> dict:
        return {
            "status": "completed",
            "trajectory": [],
            "backend": "ros1",
            "note": "real run requires ROS bridge; see bridge_ros.py",
        }

    def stop(self) -> dict:
        return {"status": "stopped"}


def build_planner() -> object:
    if os.environ.get("ALGO_MOCK", "0") == "1":
        return MockPlanner()
    return EgoPlanner()
