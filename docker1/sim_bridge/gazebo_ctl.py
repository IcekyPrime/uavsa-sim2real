"""Gazebo / PX4 仿真进程控制。

真实模式下，通过子进程启动 PX4 SITL（gz_x500）；当镜像内未编译 PX4 或
`SIM_MOCK=1` 时回退到 Mock 仿真器，产出与真实一致的指标结构。
"""
from __future__ import annotations

import os
import random
import subprocess
import threading
import time

from .metrics import METRIC_KEYS


class MockGazebo:
    """无需 PX4/Gazebo 的假仿真器，产出可复现的伪指标，用于闭环演示与单测。"""

    def __init__(self, seed: int = 42):
        self._rng = random.Random(seed)
        self._running = False
        self._t0 = 0.0

    def start(self, scenario: dict | None = None) -> dict:
        self._running = True
        self._t0 = time.time()
        # 场景里的障碍物密度会影响“碰撞/平滑度”的基线
        density = (scenario or {}).get("obstacle_density", 0.5)
        self._density = density
        return {"status": "running", "backend": "mock"}

    def stop(self) -> dict:
        self._running = False
        return {"status": "stopped"}

    def metrics(self) -> dict:
        if not self._running:
            return {k: None for k in METRIC_KEYS}
        d = self._density
        return {
            "tracking_error_m": round(self._rng.uniform(0.05, 0.4) * (1 + d), 4),
            "convergence_time_s": round(self._rng.uniform(1.0, 6.0) * (1 + d), 3),
            "success_rate": round(self._rng.uniform(0.6, 0.99), 4),
            "collision_count": int(self._rng.uniform(0, 3) * d),
            "overshoot": round(self._rng.uniform(0.0, 0.3) * d, 4),
            "smoothness": round(self._rng.uniform(0.1, 0.9) * (1 + d), 4),
            "energy": round(self._rng.uniform(0.5, 1.0), 4),
            "safety_violations": int(self._rng.uniform(0, 2) * d),
            "anomaly_score": round(self._rng.uniform(0.0, 0.8), 4),
        }


class GazeboSimulator:
    """真实 Gazebo + PX4 SITL 控制。

    通过环境变量 / 命令启动 `make px4_sitl gz_x500`。若进程未编译成功，
    会抛错并建议回退 Mock 模式。
    """

    def __init__(self, model: str = "gz_x500", world: str = "default", headless: bool = True):
        self.model = model
        self.world = world
        self.headless = headless
        self._proc: subprocess.Popen | None = None

    def start(self, scenario: dict | None = None) -> dict:
        px4_dir = "/src/PX4-Autopilot"
        if not os.path.isdir(px4_dir):
            raise RuntimeError("PX4-Autopilot 未找到，请先编译或使用 Mock 模式")
        env = dict(os.environ)
        if self.headless:
            env["HEADLESS"] = "1"
        if self.world and self.world != "default":
            env["PX4_GZ_WORLD"] = self.world
        cmd = ["make", "px4_sitl", self.model]
        self._proc = subprocess.Popen(
            cmd, cwd=px4_dir, env=env,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        return {"status": "starting", "backend": "gazebo", "model": self.model}

    def stop(self) -> dict:
        if self._proc and self._proc.poll() is None:
            self._proc.terminate()
            try:
                self._proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self._proc.kill()
        self._proc = None
        return {"status": "stopped"}

    def metrics(self) -> dict:
        # v1.0 真实指标从 ros2 话题采集；此处先占位返回 None，由 algo_bridge 回填
        return {k: None for k in METRIC_KEYS}


def build_simulator() -> object:
    """根据环境变量选择仿真后端。"""
    if os.environ.get("SIM_MOCK", "0") == "1":
        return MockGazebo()
    model = os.environ.get("SIM_MODEL", "gz_x500")
    world = os.environ.get("SIM_WORLD", "default")
    headless = os.environ.get("SIM_HEADLESS", "1") == "1"
    try:
        return GazeboSimulator(model=model, world=world, headless=headless)
    except Exception:
        return MockGazebo()
