"""sim_bridge：仿真控制与指标服务（FastAPI）。

对 agent 暴露统一的仿真控制与指标读取接口。真实 Gazebo 与 Mock 后端行为一致。
"""
from __future__ import annotations

import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from .gazebo_ctl import build_simulator
from .metrics import METRIC_KEYS

app = FastAPI(title="UAVSA sim_bridge", version="0.1.0")
app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"]
)

_sim = build_simulator()


class Scenario(BaseModel):
    obstacle_density: float = 0.5
    wind_m_s: float = 0.0
    duration_s: float = 30.0


@app.get("/health")
def health():
    return {"ok": True, "backend": type(_sim).__name__}


@app.post("/scenario/start")
def start_scenario(scenario: Scenario | None = None):
    return _sim.start(scenario.model_dump() if scenario else None)


@app.post("/scenario/stop")
def stop_scenario():
    return _sim.stop()


@app.get("/metrics")
def get_metrics():
    return _sim.metrics()


@app.get("/metric_keys")
def metric_keys():
    return {"keys": METRIC_KEYS}


def main():
    import uvicorn

    port = int(os.environ.get("SIM_BRIDGE_PORT", "8001"))
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="info")


if __name__ == "__main__":
    main()
