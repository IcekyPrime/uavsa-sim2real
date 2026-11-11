"""Agent 配置：从环境变量读取，兼顾 Docker 内 / 本地 Mock 两种运行方式。"""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv


def _repo_root() -> Path | None:
    """定位包含 shared/ 的仓库根目录（本地运行的唯一事实源）。"""
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "shared").exists():
            return parent
    return None


def _default_shared_dir() -> Path:
    # Docker 内优先使用容器共享卷
    docker_shared = Path("/workspace/shared")
    if docker_shared.exists():
        return docker_shared
    root = _repo_root()
    return (root / "shared") if root else (Path.cwd() / "shared")


class Config:
    def __init__(self):
        # 尝试加载仓库根 .env
        here = Path(__file__).resolve()
        for parent in here.parents:
            env_file = parent / ".env"
            if env_file.exists():
                load_dotenv(env_file)
                break

        self.llm_api_key = os.environ.get("LLM_API_KEY", "")
        self.llm_base_url = os.environ.get("LLM_BASE_URL", "https://api.deepseek.com")
        self.llm_model = os.environ.get("LLM_MODEL", "deepseek-v4-pro")
        self.llm_max_iterations = int(os.environ.get("LLM_MAX_ITERATIONS", "5"))
        self.llm_temperature = float(os.environ.get("LLM_TEMPERATURE", "0.2"))

        self.agent_host = os.environ.get("AGENT_HOST", "0.0.0.0")
        self.agent_port = int(os.environ.get("AGENT_PORT", "8000"))

        self.sim_bridge_url = os.environ.get("SIM_BRIDGE_URL", "http://sim_bridge:8001")
        self.algo_bridge_url = os.environ.get("ALGO_BRIDGE_URL", "http://algo_bridge:8002")

        # 相对路径统一按仓库根解析，避免本地 / Docker 指向不同 shared 目录
        raw_shared = os.environ.get("SHARED_DIR", "").strip()
        if raw_shared:
            p = Path(raw_shared).expanduser()
            if not p.is_absolute():
                p = (_repo_root() or Path.cwd()) / p
            self.shared_dir = p.resolve()
        else:
            self.shared_dir = _default_shared_dir()
        self.knowledge_dir = self.shared_dir / "knowledge"
        self.results_dir = self.shared_dir / "results"
        self.workspace_dir = self.shared_dir / "workspace"
        for d in (self.knowledge_dir, self.results_dir, self.workspace_dir):
            d.mkdir(parents=True, exist_ok=True)


config = Config()
