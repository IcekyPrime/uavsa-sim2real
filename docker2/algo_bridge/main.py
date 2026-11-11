"""algo_bridge：算法封装服务（FastAPI）。

对 agent 暴露被测算法的标准化接口：build / run / patch / status / ingest。
"""
from __future__ import annotations

import os
import shutil
import time
from typing import List, Optional

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from .planner import build_planner

app = FastAPI(title="UAVSA algo_bridge", version="0.1.0")
app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"]
)

_planner = build_planner()
_WORKSPACE = os.environ.get("ALGO_WORKSPACE", "/workspace/shared/workspace")


class RunRequest(BaseModel):
    duration_s: float = 5.0


class PatchFile(BaseModel):
    path: str          # 相对 workspace 的文件路径
    content: str       # 替换后的完整内容


class PatchRequest(BaseModel):
    files: List[PatchFile]
    message: str = ""


@app.get("/health")
def health():
    return {"ok": True, "backend": type(_planner).__name__}


@app.get("/status")
def status():
    return {"backend": type(_planner).__name__, "workspace": _WORKSPACE}


@app.post("/build")
def build():
    return _planner.build()


@app.post("/run")
def run(req: Optional[RunRequest] = None):
    return _planner.run(req.duration_s if req else 5.0)


@app.post("/patch")
def patch(req: PatchRequest):
    """应用代码补丁：先备份原文件到 .bak/，再写入新内容。"""
    os.makedirs(_WORKSPACE, exist_ok=True)
    applied = []
    for f in req.files:
        target = os.path.join(_WORKSPACE, f.path.lstrip("/\\"))
        os.makedirs(os.path.dirname(target), exist_ok=True)
        # 备份
        if os.path.exists(target):
            bak = os.path.join(_WORKSPACE, ".bak", f.path.lstrip("/\\"))
            os.makedirs(os.path.dirname(bak), exist_ok=True)
            shutil.copy2(target, bak)
        with open(target, "w", encoding="utf-8") as fh:
            fh.write(f.content)
        applied.append(f.path)
    return {"status": "patched", "files": applied, "message": req.message}


@app.post("/ingest")
def ingest(data: dict):
    """接收 sim_bridge 推送的传感器数据（v1.0 预留，转发给 planner 桥接层）。"""
    return {"status": "accepted", "keys": list(data.keys())}


def main():
    import uvicorn

    port = int(os.environ.get("ALGO_BRIDGE_PORT", "8002"))
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="info")


if __name__ == "__main__":
    main()
