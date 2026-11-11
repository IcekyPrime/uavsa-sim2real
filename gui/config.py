"""GUI 本地配置：API Key、模型、Agent 地址的持久化。"""
from __future__ import annotations

import json
import sys
from pathlib import Path


def _base_dir() -> Path:
    # 打包成 exe 后，配置与可执行文件同目录；开发时与 gui/ 同目录
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent


CONFIG_PATH = _base_dir() / "uavsa_gui_config.json"

DEFAULTS = {
    "llm_api_key": "",
    "llm_model": "deepseek-v4-pro",
    "llm_base_url": "https://api.deepseek.com",
    "agent_url": "",  # 留空 = 本地内置 Mock Agent；填 http://127.0.0.1:8000 可连 Docker Agent
}


def load() -> dict:
    cfg = dict(DEFAULTS)
    if CONFIG_PATH.exists():
        try:
            cfg.update(json.loads(CONFIG_PATH.read_text(encoding="utf-8")))
        except Exception:
            pass
    return cfg


def save(cfg: dict):
    CONFIG_PATH.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
