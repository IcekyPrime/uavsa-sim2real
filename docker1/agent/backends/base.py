"""后端抽象接口：SimBackend / AlgoBackend。"""
from __future__ import annotations

from abc import ABC, abstractmethod


class SimBackend(ABC):
    """仿真后端接口（真实 sim_bridge 或 mock）。"""

    @abstractmethod
    def start_scenario(self, scenario: dict | None = None) -> dict: ...

    @abstractmethod
    def stop(self) -> dict: ...

    @abstractmethod
    def metrics(self) -> dict: ...


class AlgoBackend(ABC):
    """算法后端接口（真实 algo_bridge 或 mock）。"""

    @abstractmethod
    def build(self) -> dict: ...

    @abstractmethod
    def run(self, duration_s: float = 5.0) -> dict: ...

    @abstractmethod
    def patch(self, files: list[dict], message: str = "") -> dict: ...

    @abstractmethod
    def status(self) -> dict: ...
