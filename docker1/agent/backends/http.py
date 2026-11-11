"""HTTP 后端：通过 HTTP 调用 sim_bridge / algo_bridge 服务（Docker 模式）。"""
from __future__ import annotations

import httpx

from .base import AlgoBackend, SimBackend


class HttpSimBackend(SimBackend):
    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip("/")

    def _post(self, path: str, json: dict | None = None) -> dict:
        with httpx.Client(timeout=30) as c:
            r = c.post(f"{self.base_url}{path}", json=json)
            r.raise_for_status()
            return r.json()

    def start_scenario(self, scenario: dict | None = None) -> dict:
        return self._post("/scenario/start", scenario)

    def stop(self) -> dict:
        return self._post("/scenario/stop")

    def metrics(self) -> dict:
        with httpx.Client(timeout=30) as c:
            r = c.get(f"{self.base_url}/metrics")
            r.raise_for_status()
            return r.json()


class HttpAlgoBackend(AlgoBackend):
    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip("/")

    def _post(self, path: str, json: dict | None = None) -> dict:
        with httpx.Client(timeout=60) as c:
            r = c.post(f"{self.base_url}{path}", json=json)
            r.raise_for_status()
            return r.json()

    def build(self) -> dict:
        return self._post("/build")

    def run(self, duration_s: float = 5.0) -> dict:
        return self._post("/run", {"duration_s": duration_s})

    def patch(self, files: list[dict], message: str = "") -> dict:
        return self._post("/patch", {"files": files, "message": message})

    def status(self) -> dict:
        with httpx.Client(timeout=30) as c:
            r = c.get(f"{self.base_url}/status")
            r.raise_for_status()
            return r.json()


def make_http_backends(sim_url: str, algo_url: str) -> tuple[HttpSimBackend, HttpAlgoBackend]:
    return HttpSimBackend(sim_url), HttpAlgoBackend(algo_url)
