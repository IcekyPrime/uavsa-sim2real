"""UAVSA GUI 启动器（pywebview）。

- 内置 Agent：默认在本进程内启动 Mock Agent 服务（http://127.0.0.1:8000）。
- 若 config.agent_url 指向远程（如 Docker Agent），则不启动本地服务，直接连远程。
- 通过 js_api 暴露配置读写给前端 JS。
"""
from __future__ import annotations

import sys
import threading
from pathlib import Path

import webview

# 让 GUI 能导入 agent 包（仓库根下 docker1/agent）
_REPO = Path(__file__).resolve().parent.parent
_AGENT_PARENT = _REPO / "docker1"
if str(_AGENT_PARENT) not in sys.path:
    sys.path.insert(0, str(_AGENT_PARENT))

from agent.backends.mock import make_mock_backends  # noqa: E402
import agent.main as agent_main  # noqa: E402
import config as gui_config  # noqa: E402


LOCAL_AGENT_URL = "http://127.0.0.1:8000"


def _start_local_agent():
    """在后台线程启动内置 Mock Agent 的 HTTP 服务。"""
    sim, algo = make_mock_backends()
    agent_main.init_manager(sim, algo)

    import uvicorn
    from agent.main import app

    def _serve():
        uvicorn.run(app, host="127.0.0.1", port=8000, log_level="warning")

    threading.Thread(target=_serve, daemon=True).start()


class Api:
    def get_config(self):
        return gui_config.load()

    def save_config(self, cfg: dict):
        gui_config.save(cfg)
        return {"ok": True}

    def get_agent_url(self):
        cfg = gui_config.load()
        return cfg.get("agent_url") or LOCAL_AGENT_URL

    def is_local(self):
        cfg = gui_config.load()
        return not cfg.get("agent_url")

    def pick_file(self):
        """弹出文件选择框，返回所选文件路径（取消返回 None）。"""
        try:
            window = webview.windows[0]
            result = window.create_file_dialog(webview.OPEN_DIALOG, allow_multiple=False)
            if isinstance(result, (list, tuple)) and result:
                return result[0]
            return result or None
        except Exception:
            return None


def main():
    cfg = gui_config.load()
    if not cfg.get("agent_url"):
        _start_local_agent()

    api = Api()
    index_html = str(Path(__file__).resolve().parent / "index.html")
    window = webview.create_window(
        "UAVSA · 无人机算法 Harness 平台",
        index_html,
        js_api=api,
        width=1100,
        height=760,
        min_size=(880, 600),
    )
    webview.start(debug=False)


if __name__ == "__main__":
    main()
