"""Agent 服务入口：FastAPI（供 GUI 连接）+ CLI（单次运行 / 自测）。

用法：
  python -m agent.main --mock          # 本地 Mock 后端，启动 HTTP 服务（GUI 可连）
  python -m agent.main --docker        # Docker 模式，连接 sim_bridge / algo_bridge
  python -m agent.main --cli "目标"    # 单次运行并打印结果
"""
from __future__ import annotations

import argparse
import json
import threading
from typing import Optional

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from .backends.http import make_http_backends
from .backends.mock import make_mock_backends
from .config import config
from .llm import LLMClient
from .loop import Agent

try:
    from .backends.ssh import make_ssh_backends
except Exception:  # 无 paramiko 时降级（不影响 mock/docker 模式）
    make_ssh_backends = None

app = FastAPI(title="UAVSA agent", version="0.1.0")
app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"]
)

# 运行期可被 /config 覆盖的 LLM 配置
_runtime_llm: dict = {"api_key": "", "model": ""}


class SessionRequest(BaseModel):
    goal: str
    algorithm: str = ""
    llm_api_key: Optional[str] = None
    llm_model: Optional[str] = None


# ---- 会话管理（后台线程 + 事件缓冲） ----
class SessionManager:
    def __init__(self, sim, algo):
        self.sim = sim
        self.algo = algo
        self._sessions: dict[str, dict] = {}
        self._lock = threading.Lock()

    def start(self, req: SessionRequest) -> str:
        sid = f"sess-{int(threading.get_ident())}-{len(self._sessions)}"
        self._sessions[sid] = {"events": [], "done": False, "result": None, "goal": req.goal}

        api_key = req.llm_api_key or _runtime_llm.get("api_key") or config.llm_api_key
        model = req.llm_model or _runtime_llm.get("model") or config.llm_model
        client = LLMClient(api_key=api_key, model=model)
        agent = Agent(self.sim, self.algo, config=config, llm_client=client)

        def _run():
            def emit(event):
                with self._lock:
                    self._sessions[sid]["events"].append(event)
            result = agent.run(req.goal, req.algorithm, progress=emit)
            with self._lock:
                self._sessions[sid]["done"] = True
                self._sessions[sid]["result"] = result

        threading.Thread(target=_run, daemon=True).start()
        return sid

    def status(self, sid: str) -> dict:
        with self._lock:
            s = self._sessions.get(sid)
            if not s:
                return {"error": "session not found"}
            return {"id": sid, "done": s["done"], "goal": s["goal"], "events": s["events"], "result": s["result"]}

    def new_events(self, sid: str, after: int) -> tuple[list[dict], int]:
        with self._lock:
            s = self._sessions.get(sid)
            if not s:
                return [], after
            ev = s["events"]
            new = ev[after:]
            return new, len(ev)


_manager: SessionManager | None = None


def init_manager(sim, algo) -> SessionManager:
    """供 GUI / 嵌入式运行复用：初始化会话管理器（返回后即可启动 uvicorn）。"""
    global _manager
    _manager = SessionManager(sim, algo)
    return _manager


@app.get("/health")
def health():
    return {"ok": True, "backend": type(_manager.sim).__name__ if _manager else "none"}


@app.get("/config")
def get_config():
    key = _runtime_llm.get("api_key") or config.llm_api_key
    masked = (key[:4] + "****" + key[-4:]) if key else ""
    return {"llm_api_key": masked, "llm_model": _runtime_llm.get("model") or config.llm_model,
            "llm_base_url": config.llm_base_url}


@app.post("/config")
def set_config(payload: dict):
    if "llm_api_key" in payload:
        _runtime_llm["api_key"] = payload["llm_api_key"]
    if "llm_model" in payload:
        _runtime_llm["model"] = payload["llm_model"]
    return {"ok": True}


@app.post("/session")
def create_session(req: SessionRequest):
    if not _manager:
        return {"error": "agent not initialized"}
    sid = _manager.start(req)
    return {"session_id": sid}


@app.get("/session/{sid}")
def session_status(sid: str):
    return _manager.status(sid)


@app.websocket("/session/{sid}/stream")
async def stream(ws: WebSocket, sid: str):
    await ws.accept()
    sent = 0
    try:
        while True:
            new, sent = _manager.new_events(sid, sent)
            for ev in new:
                await ws.send_json(ev)
            if _manager.status(sid).get("done"):
                await ws.send_json({"type": "done"})
                break
            import asyncio
            await asyncio.sleep(0.3)
    except WebSocketDisconnect:
        pass


# ---- CLI 单次运行 ----
def run_cli(goal: str, backend: str = "mock"):
    if backend == "cluster":
        if make_ssh_backends is None:
            raise RuntimeError("SSH 后端不可用（缺少 paramiko）")
        sim, algo = make_ssh_backends()
    elif backend == "docker":
        sim, algo = make_http_backends(config.sim_bridge_url, config.algo_bridge_url)
    else:
        sim, algo = make_mock_backends()
    agent = Agent(sim, algo, config=config)
    result = agent.run(goal, "ego-planner", progress=lambda e: print(json.dumps(e, ensure_ascii=False)))
    print("=== RESULT ===")
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))


def main():
    global _manager
    parser = argparse.ArgumentParser()
    parser.add_argument("--mock", action="store_true", help="使用本地 Mock 后端")
    parser.add_argument("--docker", action="store_true", help="连接 sim_bridge/algo_bridge")
    parser.add_argument("--cluster", action="store_true", help="通过 SSH 编排集群真实 PX4/ego-planner")
    parser.add_argument("--cli", type=str, help="单次运行（传入任务目标）")
    args = parser.parse_args()

    if args.cli:
        backend = "cluster" if args.cluster else ("docker" if args.docker else "mock")
        run_cli(args.cli, backend)
        return

    if args.docker:
        sim, algo = make_http_backends(config.sim_bridge_url, config.algo_bridge_url)
    elif args.cluster:
        if make_ssh_backends is None:
            raise RuntimeError("SSH 后端不可用（缺少 paramiko）")
        sim, algo = make_ssh_backends()
    else:
        sim, algo = make_mock_backends()

    _manager = SessionManager(sim, algo)

    import uvicorn
    uvicorn.run(app, host=config.agent_host, port=config.agent_port, log_level="info")


if __name__ == "__main__":
    main()
