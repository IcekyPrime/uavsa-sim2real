"""Mock 后端：无需 Docker 即可跑通完整闭环。

用内存假数据模拟 sim_bridge / algo_bridge，指标随「补丁」次数单调改善，
便于直观演示「跑 → 看 → 改 → 重跑」的自适应过程。
"""
from __future__ import annotations

import random
import time

from .base import AlgoBackend, SimBackend

_METRIC_KEYS = [
    "tracking_error_m", "convergence_time_s", "success_rate", "collision_count",
    "overshoot", "smoothness", "energy", "safety_violations", "anomaly_score",
]


class MockSimBackend(SimBackend):
    def __init__(self):
        self._rng = random.Random(42)
        self._running = False
        self._iter = 0

    def start_scenario(self, scenario: dict | None = None) -> dict:
        self._running = True
        self._density = (scenario or {}).get("obstacle_density", 0.5)
        return {"status": "running", "backend": "mock"}

    def stop(self) -> dict:
        self._running = False
        return {"status": "stopped"}

    def metrics(self) -> dict:
        if not self._running:
            return {k: None for k in _METRIC_KEYS}
        d = self._density
        # 每读一次指标视为一轮迭代，逐步改善（叠加噪声，模拟补丁的混合效果）
        improve = max(0.0, 1.0 - 0.22 * self._iter)
        self._iter += 1
        return {
            "tracking_error_m": round(self._rng.uniform(0.05, 0.4) * (1 + d) * improve + 0.02, 4),
            "convergence_time_s": round(self._rng.uniform(1.0, 6.0) * (1 + d) * improve + 0.2, 3),
            "success_rate": round(min(0.99, 0.55 + 0.07 * (self._iter - 1)), 4),
            "collision_count": max(0, int(self._rng.uniform(0, 3) * d * improve)),
            "overshoot": round(self._rng.uniform(0.0, 0.3) * d * improve, 4),
            "smoothness": round(self._rng.uniform(0.1, 0.9) * (1 + d) * improve + 0.05, 4),
            "energy": round(self._rng.uniform(0.5, 1.0) * improve + 0.2, 4),
            "safety_violations": max(0, int(self._rng.uniform(0, 2) * d * improve)),
            "anomaly_score": round(self._rng.uniform(0.0, 0.8) * improve, 4),
        }

    def set_iteration(self, i: int):
        self._iter = i


class MockAlgoBackend(AlgoBackend):
    def __init__(self):
        self._built = False

    def build(self) -> dict:
        time.sleep(0.15)
        self._built = True
        return {"status": "built", "backend": "mock"}

    def run(self, duration_s: float = 5.0) -> dict:
        n = max(2, int(duration_s * 10))
        traj = [
            {"t": round(i * 0.1, 2), "x": round(i * 0.1, 3),
             "y": round(random.uniform(-0.3, 0.3), 3), "z": round(1.0, 3)}
            for i in range(n)
        ]
        return {"status": "completed", "trajectory_length": n, "trajectory": traj, "backend": "mock"}

    def patch(self, files: list[dict], message: str = "") -> dict:
        return {"status": "patched", "files": [f["path"] for f in files], "message": message}

    def status(self) -> dict:
        return {"backend": "mock", "built": self._built}


def make_mock_backends() -> tuple[MockSimBackend, MockAlgoBackend]:
    return MockSimBackend(), MockAlgoBackend()
